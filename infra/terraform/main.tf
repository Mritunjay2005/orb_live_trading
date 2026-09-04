terraform {
  required_version = ">= 1.5.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0.0"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
resource "oci_core_vcn" "orb" {
  compartment_id = var.compartment_ocid
  display_name   = "orb-vcn"
  cidr_blocks    = ["10.0.0.0/16"]
  dns_label      = "orbvcn"
}

resource "oci_core_internet_gateway" "orb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.orb.id
  display_name   = "orb-igw"
  enabled        = true
}

resource "oci_core_route_table" "orb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.orb.id
  display_name   = "orb-rt"
  route_rules {
    network_entity_id = oci_core_internet_gateway.orb.id
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
  }
}

resource "oci_core_security_list" "orb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.orb.id
  display_name   = "orb-sl"

  # SSH only from your IP
  ingress_security_rules {
    protocol    = "6"
    source      = var.ssh_ingress_cidr
    source_type = "CIDR_BLOCK"
    tcp_options {
      min = 22
      max = 22
    }
  }

  # Grafana
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    tcp_options {
      min = 3000
      max = 3000
    }
  }

  # Prometheus (optional – restrict later)
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    tcp_options {
      min = 9090
      max = 9090
    }
  }

  # Metrics from trading process (internal, but open for simplicity on free tier)
  ingress_security_rules {
    protocol    = "6"
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    tcp_options {
      min = 8000
      max = 8000
    }
  }

  egress_security_rules {
    protocol         = "all"
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
  }
}

resource "oci_core_subnet" "orb_public" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.orb.id
  display_name               = "orb-public"
  cidr_block                 = "10.0.1.0/24"
  route_table_id             = oci_core_route_table.orb.id
  security_list_ids          = [oci_core_security_list.orb.id]
  prohibit_public_ip_on_vnic = false
  dns_label                  = "orbpublic"
}

# ---------------------------------------------------------------------------
# Compute – Always Free Ampere A1
# ---------------------------------------------------------------------------
# We first give the instance an ephemeral public IP so it is reachable.
# Immediately after apply, convert it to a RESERVED public IP in the OCI
# console (Networking → Public IPs → create reserved + assign to the VNIC).
# That reserved IP is the one you whitelist in Upstox. It stays stable
# across stop/start.
resource "oci_core_instance" "orb" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = var.instance_display_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.ampere_ocpus
    memory_in_gbs = var.ampere_memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.orb_public.id
    assign_public_ip = true
    display_name     = "orb-vnic"
    hostname_label   = "orb"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  timeouts {
    create = "30m"
  }
}
