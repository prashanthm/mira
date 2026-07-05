variable "container_image" {
  type        = string
  description = "ECR image URI for the Mira agent container."
  default     = "ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/mira:latest"
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.name_prefix}"
  retention_in_days = 90
}

resource "aws_ecs_cluster" "agent" {
  name = "${var.name_prefix}-cluster"
}

resource "aws_ecs_task_definition" "agent" {
  family                   = var.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = var.name_prefix
    image     = var.container_image
    essential = true
    user      = "1000:1000"
    portMappings = [{
      containerPort = var.agent_port
      protocol      = "tcp"
    }]
    readonlyRootFilesystem = true
    mountPoints = [{
      sourceVolume  = "tmp"
      containerPath = "/tmp"
      readOnly      = false
    }]
    linuxParameters = {
      capabilities = {
        drop = ["ALL"]
      }
    }
    environment = [{
      name  = "DEPLOYMENT_PROFILE"
      value = "saas"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ecs.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = var.name_prefix
      }
    }
    # Probe uses the app's own Python runtime rather than curl: hardened minimal
    # base images often omit curl, which (with readonlyRootFilesystem) would fail
    # health checks and cycle the task. The base image contract (Python 3.12+)
    # is documented in README.md.
    healthCheck = {
      command = ["CMD-SHELL",
        "python3 -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${var.agent_port}/health', timeout=3).status==200 else 1)\" || exit 1"
      ]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  volume {
    name = "tmp"
  }

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
}

resource "aws_ecs_service" "agent" {
  name            = "${var.name_prefix}-service"
  cluster         = aws_ecs_cluster.agent.id
  task_definition = aws_ecs_task_definition.agent.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [for s in aws_subnet.private : s.id]
    security_groups  = [aws_security_group.agent.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.agent.arn
    container_name   = var.name_prefix
    container_port   = var.agent_port
  }

  depends_on = [aws_lb_listener.https]
}
