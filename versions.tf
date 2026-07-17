terraform {
  required_providers {
    aws = {
      version = "~> 6.0"
      source  = "hashicorp/aws"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
    external = {
      source  = "hashicorp/external"
      version = ">= 2.3.0"
    }
  }
  required_version = "~> 1.0"
}
