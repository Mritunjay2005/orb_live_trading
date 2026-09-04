variable "tenancy_ocid" {
  description = "OCI tenancy OCID"
  type        = string
}

variable "user_ocid" {
  description = "OCI user OCID"
  type        = string
}

variable "fingerprint" {
  description = "API key fingerprint"
  type        = string
}

variable "private_key_path" {
  description = "Path to the OCI API private key PEM"
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment OCID (usually the root compartment for free tier)"
  type        = string
}

variable "region" {
  description = "OCI region"
  type        = string
  default     = "ap-mumbai-1"
}

variable "ssh_public_key" {
  description = "SSH public key for the opc user"
  type        = string
}

variable "ssh_ingress_cidr" {
  description = "Your public IP in CIDR form for SSH (e.g. 1.2.3.4/32)"
  type        = string
}

variable "instance_display_name" {
  type    = string
  default = "orb-live-trading"
}

variable "ampere_ocpus" {
  type    = number
  default = 2
}

variable "ampere_memory_gb" {
  type    = number
  default = 12
}
