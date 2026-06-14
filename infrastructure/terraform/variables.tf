# Input variables for the EDGAR-X AWS infrastructure.
# All have safe, non-secret defaults; override via terraform.tfvars (see
# terraform.tfvars.example). No variable here holds a credential — secret
# VALUES are injected into Secrets Manager out-of-band, never via Terraform.

variable "project" {
  description = "Project name, used as a resource-name prefix."
  type        = string
  default     = "edgar-x"
}

variable "environment" {
  description = "Deployment environment (e.g. dev, staging, prod)."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to span (2 minimum for EKS)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2
    error_message = "EKS requires subnets in at least two availability zones."
  }
}

variable "kubernetes_version" {
  description = "EKS control-plane Kubernetes version."
  type        = string
  default     = "1.30"
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_desired_size" {
  description = "Desired number of worker nodes."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum number of worker nodes."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum number of worker nodes."
  type        = number
  default     = 4
}

variable "ecr_repositories" {
  description = "ECR repositories to create, one per service image."
  type        = list(string)
  default     = ["agents", "api", "dashboard", "jobs"]
}
