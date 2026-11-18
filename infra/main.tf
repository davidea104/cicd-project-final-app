# infra/main.tf — Kuadra en AWS (un workspace por ambiente: staging y production)
#
#   Usuario ──HTTPS──► API Gateway (HTTP API) ──► ALB ──► ECS Fargate (Flask)
#                                                            ├──► DynamoDB (datos)
#                                                            └──► Secrets Manager (claves)
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # La configuración del bucket se pasa con "terraform init -backend-config=backend.hcl"
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "kuadra"
      Environment = var.environment_name
      ManagedBy   = "Terraform"
    }
  }
}

locals {
  name_prefix    = "kuadra-${var.environment_name}"
  container_name = "kuadra"
  container_port = 8000
  es_staging     = var.environment_name == "staging"
}

# --- Recursos existentes de AWS Academy que Terraform solo consulta ---

data "aws_iam_role" "lab_role" {
  name = "LabRole"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }

  filter {
    name   = "availability-zone"
    values = ["${var.aws_region}a", "${var.aws_region}b"]
  }
}

# --- Datos: DynamoDB (una sola tabla, claves PK/SK) ---

resource "aws_dynamodb_table" "datos" {
  name         = local.name_prefix
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  point_in_time_recovery {
    enabled = !local.es_staging
  }

  server_side_encryption {
    enabled = true
  }
}

# --- Secretos: Secrets Manager (nunca en el código ni en la imagen) ---

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name_prefix}-app"
  description             = "Claves de Kuadra (${var.environment_name})"
  recovery_window_in_days = 0 # permite destruir y recrear el ambiente sin esperar
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    SECRET_KEY           = random_password.secret_key.result
    GEMINI_API_KEY       = var.gemini_api_key
    GOOGLE_CLIENT_ID     = var.google_client_id
    GOOGLE_CLIENT_SECRET = var.google_client_secret
    # El token de pruebas solo existe en staging
    TOKEN_PRUEBAS = local.es_staging ? var.token_pruebas : ""
  })
}

# --- Logs ---

resource "aws_cloudwatch_log_group" "ecs_logs" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/apigateway/${local.name_prefix}"
  retention_in_days = 30
}

# --- Cluster ECS ---

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"
}

# --- Security Groups ---

resource "aws_security_group" "alb_sg" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Permite trafico HTTP hacia el ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP desde Internet (API Gateway)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs_service_sg" {
  name        = "${local.name_prefix}-ecs-sg"
  description = "Permite trafico al puerto 8000 solo desde el ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Trafico desde el ALB"
    from_port       = local.container_port
    to_port         = local.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- Application Load Balancer ---

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "app" {
  name                 = "${local.name_prefix}-tg"
  port                 = local.container_port
  protocol             = "HTTP"
  vpc_id               = data.aws_vpc.default.id
  target_type          = "ip"
  deregistration_delay = 30

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# --- HTTPS: API Gateway (HTTP API) delante del ALB ---
# Google exige HTTPS para el login y AWS Academy no permite CloudFront:
# API Gateway entrega una URL https://<id>.execute-api.<region>.amazonaws.com sin dominio propio.

resource "aws_apigatewayv2_api" "https" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "Entrada HTTPS de Kuadra (${var.environment_name})"
}

resource "aws_apigatewayv2_integration" "raiz" {
  api_id             = aws_apigatewayv2_api.https.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = "http://${aws_lb.main.dns_name}/"
}

resource "aws_apigatewayv2_integration" "rutas" {
  api_id             = aws_apigatewayv2_api.https.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = "http://${aws_lb.main.dns_name}/{proxy}"
}

resource "aws_apigatewayv2_route" "raiz" {
  api_id    = aws_apigatewayv2_api.https.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.raiz.id}"
}

resource "aws_apigatewayv2_route" "rutas" {
  api_id    = aws_apigatewayv2_api.https.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.rutas.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.https.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  # Registro de cada petición (sin cuerpo ni cabeceras: no guarda datos personales)
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_logs.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      metodo    = "$context.httpMethod"
      ruta      = "$context.path"
      estado    = "$context.status"
      latencia  = "$context.responseLatency"
      fecha     = "$context.requestTime"
    })
  }
}

# --- Task Definition ---

resource "aws_ecs_task_definition" "app" {
  family                   = "${local.name_prefix}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = data.aws_iam_role.lab_role.arn
  task_role_arn            = data.aws_iam_role.lab_role.arn

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = var.docker_image_uri
      essential = true
      portMappings = [
        {
          containerPort = local.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_VERSION", value = var.app_version },
        { name = "AMBIENTE", value = var.environment_name },
        { name = "MODO_DEMO", value = local.es_staging ? "true" : "false" },
        { name = "COOKIE_SEGURA", value = "true" },
        { name = "DYNAMODB_TABLA", value = aws_dynamodb_table.datos.name },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "URL_PUBLICA", value = aws_apigatewayv2_api.https.api_endpoint },
      ]
      # Cada clave se lee de Secrets Manager al arrancar la tarea
      secrets = [
        for clave in ["SECRET_KEY", "GEMINI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_PRUEBAS"] : {
          name      = clave
          valueFrom = "${aws_secretsmanager_secret.app.arn}:${clave}::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs_logs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  depends_on = [aws_secretsmanager_secret_version.app]
}

# --- Servicio ECS ---

resource "aws_ecs_service" "app" {
  name            = "${local.name_prefix}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Si la tarea nueva no queda sana, ECS vuelve sola a la versión anterior
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  wait_for_steady_state = true

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_service_sg.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = local.container_name
    container_port   = local.container_port
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener.http]
}
