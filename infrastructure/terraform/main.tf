###############################################################################
# EDGAR-X — AWS infrastructure as code.
#
# ⚠ DEPLOYMENT-READY, NOT DEPLOYED.
#
# This configuration is complete and `terraform validate` / `terraform fmt`
# clean, but it has intentionally NOT been applied to any AWS account. Running
# `terraform apply` WOULD provision billable resources (an EKS control plane,
# NAT gateway, EC2 worker nodes, etc.) — do not apply it casually. No real
# credentials, account IDs, or secrets are committed here.
#
# What it describes: the AWS architecture EDGAR-X would run on — a VPC with
# public/private subnets across two AZs, an EKS cluster + managed node group,
# ECR repositories for the service images, the IAM roles those need, and
# Secrets Manager *containers* (no values) for the Snowflake / Anthropic
# credentials that a deployment would inject out-of-band.
###############################################################################

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Remote state backend — commented out so `terraform init` works locally
  # without a real S3 bucket. A live deployment would enable and own this.
  # backend "s3" {
  #   bucket         = "edgar-x-terraform-state"
  #   key            = "edgar-x/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "edgar-x-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "edgar-x"
      ManagedBy = "terraform"
      Status    = "deployment-ready-not-deployed"
    }
  }
}

locals {
  name = "${var.project}-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}
