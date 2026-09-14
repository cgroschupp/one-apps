import base64

from one_vrouter.context import build_model
from one_vrouter.vyos.renderer import render


def lines(env, onegate=None):
    return [command.render() for command in render(build_model(env, onegate)).commands]


def test_interfaces_router_nat_and_management_exclusion():
    env = {
        "VROUTER_ID": "42",
        "ETH0_IP": "203.0.113.10/24",
        "ETH1_IP": "10.0.0.1/24",
        "ETH1_VROUTER_MANAGEMENT": "YES",
        "ONEAPP_VNF_NAT4_ENABLED": "YES",
        "ONEAPP_VNF_NAT4_INTERFACES_OUT": "eth0 eth1",
        "ONEAPP_VNF_NAT4_PORT_FWD0": "8080:10.0.0.20:80",
    }
    output = lines(env)
    assert "delete system ip disable-forwarding" in output
    assert "delete interfaces ethernet eth0 ip disable-forwarding" in output
    assert "set interfaces ethernet eth1 ip disable-forwarding" in output
    assert "set nat source rule 9000 outbound-interface name eth0" in output
    assert not any("outbound-interface name eth1" in line for line in output)
    assert "set nat destination rule 10000 translation address 10.0.0.20" in output


def test_vrrp_owns_vips_instead_of_static_interface():
    env = {
        "VMID": "12",
        "ETH0_IP": "192.0.2.12/24",
        "ONEAPP_VROUTER_ETH0_VIP0": "192.0.2.1/24",
    }
    output = lines(env)
    assert "set high-availability vrrp group ONE-ETH0 interface eth0" in output
    assert "set high-availability vrrp group ONE-ETH0 vrid 13" in output
    assert "set high-availability vrrp group ONE-ETH0 address 192.0.2.1/24" in output
    assert "set interfaces ethernet eth0 address 192.0.2.1/24" not in output


def test_dhcp_and_dns_native_services():
    env = {
        "ETH0_IP": "10.20.30.1/24",
        "ONEAPP_VNF_DHCP4_ENABLED": "YES",
        "ONEAPP_VNF_DHCP4_GATEWAY": "<ETH0_IP0>",
        "ONEAPP_VNF_DNS_ENABLED": "YES",
        "ONEAPP_VNF_DNS_NAMESERVERS": "1.1.1.1 8.8.8.8",
    }
    output = lines(env)
    root = "set service dhcp-server shared-network-name ETH0 subnet 10.20.30.0/24"
    assert f"{root} range 0 start 10.20.30.2" in output
    assert f"{root} range 0 stop 10.20.30.254" in output
    assert f"{root} option default-router 10.20.30.1" in output
    assert "set service dns forwarding listen-address 10.20.30.1" in output
    assert "set service dns forwarding allow-from 10.20.30.0/24" in output


def test_sdnat_uses_external_and_parent_network_leases():
    env = {
        "ETH0_IP": "10.0.0.1/24",
        "ONEAPP_VNF_SDNAT4_ENABLED": "YES",
        "ONEAPP_VNF_SDNAT4_INTERFACES": "eth0",
    }
    onegate = {
        "vnets": [
            {"VNET": {"ID": "10", "AR_POOL": {"AR": {"LEASES": {"LEASE": {"VM": "9", "IP": "10.0.0.9"}}}}}},
            {"VNET": {"ID": "20", "AR_POOL": {"AR": {"LEASES": {"LEASE": {"VM": "9", "IP": "198.51.100.9", "EXTERNAL": "YES", "PARENT_NETWORK_ID": "10"}}}}}},
        ]
    }
    output = lines(env, onegate)
    assert "set interfaces loopback lo address 198.51.100.9/32" in output
    assert "set nat source rule 20000 translation address 198.51.100.9" in output
    assert "set nat destination rule 30000 translation address 10.0.0.9" in output


def test_ipvs_and_haproxy_rendering():
    env = {
        "ETH0_IP": "192.0.2.1/24",
        "ONEAPP_VROUTER_ETH0_VIP0": "192.0.2.50/24",
        "ONEAPP_VROUTER_ETH0_VIP1": "192.0.2.60/24",
        "ONEAPP_VNF_LB_ENABLED": "YES",
        "ONEAPP_VNF_LB0_IP": "192.0.2.50",
        "ONEAPP_VNF_LB0_PORT": "443",
        "ONEAPP_VNF_LB0_SERVER0_HOST": "10.0.0.10",
        "ONEAPP_VNF_LB0_SERVER0_PORT": "8443",
        "ONEAPP_VNF_HAPROXY_ENABLED": "YES",
        "ONEAPP_VNF_HAPROXY_LB0_IP": "192.0.2.60",
        "ONEAPP_VNF_HAPROXY_LB0_PORT": "80",
        "ONEAPP_VNF_HAPROXY_LB0_SERVER0_HOST": "10.0.0.20",
        "ONEAPP_VNF_HAPROXY_LB0_SERVER0_PORT": "8080",
    }
    output = lines(env)
    assert "set high-availability virtual-server 192.0.2.50 real-server 10.0.0.10 port 8443" in output
    assert "set load-balancing haproxy service one-lb-0 listen-address 192.0.2.60" in output
    assert "set load-balancing haproxy backend one-backend-0 server server-0 address 10.0.0.20" in output


def test_wireguard_imported_server_config():
    server = """[Interface]\nAddress = 169.254.33.1/24\nListenPort = 51820\nPrivateKey = secret\n\n[Peer]\nPublicKey = public\nPresharedKey = shared\nAllowedIPs = 169.254.33.2/32\n"""
    env = {
        "ETH0_IP": "192.0.2.1/24",
        "ONEAPP_VNF_WG_ENABLED": "YES",
        "ONEGATE_VNF_WG_SERVER": base64.b64encode(server.encode()).decode(),
    }
    output = lines(env)
    assert "set interfaces wireguard wg0 address 169.254.33.1/24" in output
    assert "set interfaces wireguard wg0 peer peer-0 public-key public" in output
