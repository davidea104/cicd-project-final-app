# infra/outputs.tf
output "app_url" {
  description = "URL pública HTTPS de la app (API Gateway)"
  value       = aws_apigatewayv2_api.https.api_endpoint
}

output "alb_url" {
  description = "URL interna del ALB (HTTP, detrás de API Gateway)"
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecs_cluster_name" {
  description = "Nombre del cluster ECS"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Nombre del servicio ECS"
  value       = aws_ecs_service.app.name
}

output "dynamodb_table" {
  description = "Tabla DynamoDB del ambiente"
  value       = aws_dynamodb_table.datos.name
}

output "google_redirect_uri" {
  description = "URI de redirección a registrar en Google Cloud para este ambiente"
  value       = "${aws_apigatewayv2_api.https.api_endpoint}/auth/google/callback"
}
