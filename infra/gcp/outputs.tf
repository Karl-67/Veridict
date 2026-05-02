output "gar_url" {
  description = "Base URL for the Artifact Registry Docker repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.veridict.repository_id}"
}

output "gke_cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.veridict.name
}

output "project_id" {
  description = "GCP project ID"
  value       = var.project_id
}

output "region" {
  description = "GCP region"
  value       = var.region
}

output "datasets_bucket" {
  description = "GCS bucket for training datasets"
  value       = google_storage_bucket.datasets.name
}

output "artifacts_bucket" {
  description = "GCS bucket for MLflow artifacts"
  value       = google_storage_bucket.artifacts.name
}
