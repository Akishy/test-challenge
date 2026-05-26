global
    log stdout format raw local0

defaults
    log global
    mode tcp
    option tcplog
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend public
    bind *:80
    default_backend nginx_nodes

backend nginx_nodes
    balance roundrobin
$backend_servers
