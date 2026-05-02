# dev.tfvars — override defaults for the dev environment.
# Usage: terraform apply -var-file=dev.tfvars

project_id            = "veridict"
region                = "europe-west1"
environment           = "dev"
gke_system_node_count = 2
gke_gpu_node_count    = 0   # scale GPU pool to zero until fine-tuning is needed
