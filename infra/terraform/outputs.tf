output "instance_id" {
  value = oci_core_instance.orb.id
}

output "public_ip" {
  description = "Current public IP. Convert to RESERVED in OCI console for a stable Upstox whitelist address."
  value       = oci_core_instance.orb.public_ip
}

output "ssh_command" {
  value = "ssh -i <your-private-key> opc@${oci_core_instance.orb.public_ip}"
}

output "grafana_url" {
  value = "http://${oci_core_instance.orb.public_ip}:3000"
}

output "prometheus_url" {
  value = "http://${oci_core_instance.orb.public_ip}:9090"
}

output "metrics_url" {
  value = "http://${oci_core_instance.orb.public_ip}:8000/metrics"
}
