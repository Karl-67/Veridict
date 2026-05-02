variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "gke_system_node_count" {
  description = "Number of nodes in the system node pool"
  type        = number
  default     = 2
}

variable "gke_gpu_node_count" {
  description = "Initial number of nodes in the GPU node pool (0 = scale-to-zero)"
  type        = number
  default     = 0
}
