output "instance_ssh" {
  value = "ssh ubuntu@${oci_core_instance.trading_host.public_ip}"
}
