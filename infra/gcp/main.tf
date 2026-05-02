terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ─── Enable required APIs ────────────────────────────────────────────────────

locals {
  apis = [
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

# ─── Artifact Registry ───────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "veridict" {
  repository_id = "veridict"
  location      = var.region
  format        = "DOCKER"
  description   = "Veridict container images"

  depends_on = [google_project_service.apis]
}

# ─── GKE Cluster ────────────────────────────────────────────────────────────

resource "google_container_cluster" "veridict" {
  name             = "veridict-${var.environment}-gke"
  location         = var.region
  resource_labels  = { environment = var.environment }

  # We define node pools separately; remove the default one.
  remove_default_node_pool = true
  initial_node_count       = 1

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  depends_on = [google_project_service.apis]
}

# System node pool — e2-standard-4 (4 vCPU, 16 GB) × 2 nodes
resource "google_container_node_pool" "system" {
  name       = "system"
  cluster    = google_container_cluster.veridict.id
  node_count = var.gke_system_node_count

  node_config {
    machine_type = "e2-standard-4"
    disk_type    = "pd-ssd"
    disk_size_gb = 100

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    labels = { pool = "system", environment = var.environment }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# GPU node pool — g2-standard-4 (NVIDIA L4) — initially 0 nodes
resource "google_container_node_pool" "gpu" {
  name               = "gpu"
  cluster            = google_container_cluster.veridict.id
  initial_node_count = var.gke_gpu_node_count

  autoscaling {
    min_node_count = 0
    max_node_count = 4
  }

  node_config {
    machine_type = "g2-standard-4"
    disk_type    = "pd-ssd"
    disk_size_gb = 200

    guest_accelerator {
      type  = "nvidia-l4"
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "LATEST"
      }
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    taint {
      key    = "sku"
      value  = "gpu"
      effect = "NO_SCHEDULE"
    }

    labels = { pool = "gpu", environment = var.environment }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# ─── GCS Buckets ─────────────────────────────────────────────────────────────

resource "google_storage_bucket" "datasets" {
  name                        = "veridict-${var.environment}-datasets"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  labels                      = { environment = var.environment }
}

resource "google_storage_bucket" "artifacts" {
  name                        = "veridict-${var.environment}-artifacts"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  labels                      = { environment = var.environment }
}

resource "google_storage_bucket" "rag" {
  name                        = "veridict-${var.environment}-rag"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  labels                      = { environment = var.environment }
}

# ─── Workload Identity Service Account ───────────────────────────────────────

resource "google_service_account" "veridict_gke" {
  account_id   = "veridict-gke-sa"
  display_name = "Veridict GKE Workload Identity SA"
}

resource "google_project_iam_member" "gar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.veridict_gke.email}"
}

resource "google_project_iam_member" "storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.veridict_gke.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.veridict_gke.email}"
}

# Allow the GKE node SA to pull images from GAR
resource "google_artifact_registry_repository_iam_member" "node_puller" {
  repository = google_artifact_registry_repository.veridict.name
  location   = var.region
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.veridict_gke.email}"
}
