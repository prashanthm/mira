terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "name_prefix" {
  type    = string
  default = "mira"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "agent_port" {
  type    = number
  default = 8080
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate ARN for ALB HTTPS termination."
}

variable "allowed_egress_cidrs" {
  type        = list(string)
  description = "Explicit HTTPS egress destinations (MCP, IdP JWKS, connector endpoints)."
  default     = []
}

variable "bedrock_model_arns" {
  type        = list(string)
  description = "Allow-listed Bedrock foundation-model ARNs the task role may invoke (ADR-048 §3). Narrow before production. Empty (default) falls back to the region-wide foundation-model ARN."
  default     = []
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs                 = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets     = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets      = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]
  interface_endpoints = ["bedrock-runtime", "logs", "xray", "ssm", "secretsmanager", "ecr.api", "ecr.dkr", "sts"]
}

resource "aws_vpc" "agent" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_subnet" "private" {
  for_each                = { for idx, az in local.azs : az => local.private_subnets[idx] }
  vpc_id                  = aws_vpc.agent.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name_prefix}-private-${each.key}" }
}

resource "aws_subnet" "public" {
  for_each                = { for idx, az in local.azs : az => local.public_subnets[idx] }
  vpc_id                  = aws_vpc.agent.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name_prefix}-public-${each.key}" }
}

resource "aws_internet_gateway" "agent" {
  vpc_id = aws_vpc.agent.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.name_prefix}-nat-eip" }
}

resource "aws_nat_gateway" "agent" {
  allocation_id = aws_eip.nat.id
  subnet_id     = values(aws_subnet.public)[0].id
  tags          = { Name = "${var.name_prefix}-nat" }
  depends_on    = [aws_internet_gateway.agent]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.agent.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.agent.id
  }
  tags = { Name = "${var.name_prefix}-public-rt" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.agent.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.agent.id
  }
  tags = { Name = "${var.name_prefix}-private-rt" }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "aws_cloudwatch_log_group" "vpc_flow" {
  name              = "/vpc/flow/${var.name_prefix}"
  retention_in_days = 90
}

resource "aws_flow_log" "agent" {
  vpc_id          = aws_vpc.agent.id
  traffic_type    = "ALL"
  log_destination = aws_cloudwatch_log_group.vpc_flow.arn
  iam_role_arn    = aws_iam_role.flow_log.arn
  tags            = { Name = "${var.name_prefix}-flow-log" }
}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Internet-facing ALB ingress."
  vpc_id      = aws_vpc.agent.id
  tags        = { Name = "${var.name_prefix}-alb-sg" }
}

resource "aws_security_group" "agent" {
  name        = "${var.name_prefix}-agent"
  description = "Private agent tasks with restricted egress."
  vpc_id      = aws_vpc.agent.id
  tags        = { Name = "${var.name_prefix}-agent-sg" }
}

resource "aws_security_group" "endpoint" {
  name        = "${var.name_prefix}-endpoint"
  description = "Interface VPC endpoints reachable from agent tasks."
  vpc_id      = aws_vpc.agent.id
  tags        = { Name = "${var.name_prefix}-endpoint-sg" }
}

resource "aws_security_group_rule" "alb_ingress_https" {
  type              = "ingress"
  security_group_id = aws_security_group.alb.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "alb_egress_agent" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  from_port                = var.agent_port
  to_port                  = var.agent_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.agent.id
}

resource "aws_security_group_rule" "agent_ingress_alb" {
  type                     = "ingress"
  security_group_id        = aws_security_group.agent.id
  from_port                = var.agent_port
  to_port                  = var.agent_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
}

resource "aws_security_group_rule" "agent_egress_vpc" {
  type              = "egress"
  security_group_id = aws_security_group.agent.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
}

# Fargate tasks in awsvpc mode resolve via AmazonProvidedDNS (VPC base+2) on
# port 53. Interface VPC endpoints (bedrock-runtime, ecr.*, secretsmanager, ...)
# rely on private DNS, so without these rules name resolution fails and all
# endpoint traffic silently never establishes after deploy.
resource "aws_security_group_rule" "agent_egress_dns_udp" {
  type              = "egress"
  security_group_id = aws_security_group.agent.id
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = [var.vpc_cidr]
  description       = "DNS (UDP) to VPC resolver for private endpoint resolution"
}

resource "aws_security_group_rule" "agent_egress_dns_tcp" {
  type              = "egress"
  security_group_id = aws_security_group.agent.id
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  description       = "DNS (TCP) to VPC resolver for large/fallback queries"
}

resource "aws_security_group_rule" "agent_egress_allowlist" {
  for_each          = toset(var.allowed_egress_cidrs)
  type              = "egress"
  security_group_id = aws_security_group.agent.id
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [each.value]
}

resource "aws_security_group_rule" "endpoint_ingress_agent" {
  type                     = "ingress"
  security_group_id        = aws_security_group.endpoint.id
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.agent.id
}

resource "aws_lb" "agent" {
  name               = "${var.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for s in aws_subnet.public : s.id]
  tags               = { Name = "${var.name_prefix}-alb" }
}

resource "aws_lb_target_group" "agent" {
  name        = "${var.name_prefix}-tg"
  port        = var.agent_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.agent.id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.agent.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.agent.arn
  }
}

resource "aws_wafv2_web_acl" "agent" {
  name  = "${var.name_prefix}-waf"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  rule {
    name     = "rate-limit"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-rate-limit"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "aws-managed-common"
    priority = 10
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-common-rules"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "agent" {
  resource_arn = aws_lb.agent.arn
  web_acl_arn  = aws_wafv2_web_acl.agent.arn
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.agent.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(local.interface_endpoints)
  vpc_id              = aws_vpc.agent.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.endpoint.id]
  private_dns_enabled = true
}
