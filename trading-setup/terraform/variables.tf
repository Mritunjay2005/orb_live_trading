variable "tenancy_ocid"     { type = string }
variable "user_ocid"        { type = string }
variable "fingerprint"      { type = string }
variable "private_key_path" { type = string }
variable "region"           { type = string  default = "ap-mumbai-1" }
variable "compartment_ocid" { type = string }

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_rsa.pub"
}

variable "instance_ocpus" {
  type    = number
  default = 2
}

variable "instance_memory_gb" {
  type    = number
  default = 12
}

variable "instance_display_name" {
  type    = string
  default = "algo-trading-host"
}

# The repo git clones on boot - set to your own repo URL
variable "git_repo_url" {
  type    = string
  default = "https://github.com/YOUR_USERNAME/YOUR_REPO.git"
}
