from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CdnPreset:
    key: str
    name: str
    default_sni: str
    download_path: str
    description: str
    endpoints: list[str]


# Curated high-performance edge IPs and representative anycast prefixes across global PoPs
CLOUDFLARE_ENDPOINTS = [
    # IPv4 Representative Anycast Edges
    "104.16.132.229",
    "104.16.18.94",
    "104.17.151.10",
    "104.18.32.7",
    "104.19.155.6",
    "104.20.73.1",
    "104.21.64.1",
    "104.22.25.1",
    "104.24.100.1",
    "104.25.10.1",
    "104.26.1.1",
    "104.27.150.1",
    "104.28.16.1",
    "172.64.150.1",
    "172.67.180.1",
    "162.159.138.1",
    "188.114.97.1",
    "198.41.214.1",
    "108.162.193.1",
    "141.101.120.1",
    "173.245.58.1",
    "103.21.244.1",
    "103.22.200.1",
    "103.31.4.1",
    "190.93.240.1",
    "197.234.240.1",
    "131.0.72.1",
    # IPv6 Cloudflare Edges
    "2606:4700:3030::6815:15ca",
    "2606:4700:3035::ac43:94b1",
    "2606:4700:3035::ac43:a2c7",
    "2606:4700:3033::ac43:da7c",
    "2606:4700:3035::6815:15c6",
    "2606:4700:3035::ac43:9d16",
    "2400:cb00:2048:1::c629:d7a2",
    "2405:8100:8000:1::1",
    "2a06:98c0:3600::103",
]

CLOUDFRONT_ENDPOINTS = [
    # AWS CloudFront Global Edge Locations (Europe, Middle East, Asia, US)
    "13.32.181.1",
    "13.33.243.1",
    "13.35.114.1",
    "13.224.238.1",
    "13.225.103.1",
    "13.226.241.1",
    "13.227.183.1",
    "13.249.138.1",
    "18.64.8.1",
    "18.65.170.1",
    "18.66.112.1",
    "18.67.65.1",
    "52.84.162.1",
    "52.85.144.1",
    "54.192.150.1",
    "54.230.158.1",
    "54.239.168.1",
    "54.240.130.1",
    "65.8.158.1",
    "65.9.86.1",
    "99.84.208.1",
    "99.86.115.1",
    "143.204.158.1",
    "204.246.164.1",
    "205.251.196.1",
    "216.137.38.1",
]

FASTLY_ENDPOINTS = [
    # Fastly Anycast POPs (IPv4)
    "151.101.1.140",
    "151.101.65.140",
    "151.101.129.140",
    "151.101.193.140",
    "151.101.2.217",
    "151.101.66.217",
    "151.101.130.217",
    "151.101.194.217",
    "151.101.13.140",
    "151.101.77.140",
    "151.101.141.140",
    "151.101.205.140",
    "199.232.1.140",
    "199.232.65.140",
    "199.232.129.140",
    "199.232.193.140",
    "146.75.29.140",
    "146.75.33.140",
    "146.75.97.140",
    "146.75.121.140",
    # Fastly IPv6
    "2a04:4e42::217",
    "2a04:4e42:200::217",
    "2a04:4e42:400::217",
    "2a04:4e42:600::217",
]

GOOGLE_ENDPOINTS = [
    # Google Cloud Global CDN and Front-End Edges
    "34.96.114.1",
    "34.107.221.1",
    "34.120.177.1",
    "34.149.87.1",
    "35.186.224.1",
    "35.190.27.1",
    "35.227.206.1",
    "35.244.181.1",
    "142.250.180.1",
    "142.250.185.1",
    "142.250.186.1",
    "142.250.74.1",
    "172.217.16.1",
    "172.217.18.1",
    "172.217.20.1",
    "172.217.168.1",
    "216.58.208.1",
    "216.58.212.1",
    "216.58.214.1",
]

AZURE_ENDPOINTS = [
    # Microsoft Azure Front Door and Edge CDN POPs
    "13.107.246.40",
    "13.107.246.45",
    "13.107.213.40",
    "13.107.226.40",
    "204.79.197.200",
    "204.79.197.219",
    "20.150.83.1",
    "20.189.173.1",
    "40.126.32.1",
    "40.90.136.1",
    "52.178.17.1",
    "13.77.161.1",
    "51.144.164.1",
    "52.169.18.1",
    # Azure IPv6
    "2620:1ec:4::10",
    "2620:1ec:c::10",
    "2620:1ec:21::10",
]

GCORE_ENDPOINTS = [
    # Gcore Global Edge CDN Locations
    "92.223.65.1",
    "92.223.80.1",
    "92.38.130.1",
    "92.38.160.1",
    "185.193.140.1",
    "185.193.142.1",
    "146.185.201.1",
    "195.181.160.1",
    "195.181.170.1",
    "5.188.118.1",
]

CDN_PRESETS: dict[str, CdnPreset] = {
    "cloudflare": CdnPreset(
        key="cloudflare",
        name="Cloudflare (IPv4 & IPv6)",
        default_sni="speed.cloudflare.com",
        download_path="/__down?bytes={bytes}",
        description="Official Cloudflare edge anycast IPs and IPv6 blocks for Workers/Pages and reverse proxying.",
        endpoints=CLOUDFLARE_ENDPOINTS,
    ),
    "cloudfront": CdnPreset(
        key="cloudfront",
        name="Amazon CloudFront (AWS)",
        default_sni="aws.amazon.com",
        download_path="/",
        description="Amazon CloudFront global edge POPs for AWS CDN fronting and WebSocket distributions.",
        endpoints=CLOUDFRONT_ENDPOINTS,
    ),
    "fastly": CdnPreset(
        key="fastly",
        name="Fastly CDN",
        default_sni="www.fastly.com",
        download_path="/",
        description="Fastly edge anycast clusters optimized for real-time edge compute and proxy fronting.",
        endpoints=FASTLY_ENDPOINTS,
    ),
    "google": CdnPreset(
        key="google",
        name="Google Cloud CDN / Edge",
        default_sni="cloud.google.com",
        download_path="/",
        description="Google Cloud global front-end edge infrastructure and anycast addresses.",
        endpoints=GOOGLE_ENDPOINTS,
    ),
    "azure": CdnPreset(
        key="azure",
        name="Microsoft Azure / Front Door",
        default_sni="edge.microsoft.com",
        download_path="/",
        description="Microsoft Azure Front Door and Edge CDN PoP addresses.",
        endpoints=AZURE_ENDPOINTS,
    ),
    "gcore": CdnPreset(
        key="gcore",
        name="Gcore CDN",
        default_sni="gcore.com",
        download_path="/",
        description="Gcore edge nodes with extensive Middle-East, European, and Asian routing reach.",
        endpoints=GCORE_ENDPOINTS,
    ),
}


def get_all_presets() -> list[CdnPreset]:
    return list(CDN_PRESETS.values())


def get_preset(key: str) -> CdnPreset | None:
    return CDN_PRESETS.get(key)


def get_combined_all_preset() -> CdnPreset:
    all_endpoints: list[str] = []
    seen: set[str] = set()
    for preset in CDN_PRESETS.values():
        for ep in preset.endpoints:
            if ep not in seen:
                seen.add(ep)
                all_endpoints.append(ep)

    return CdnPreset(
        key="all_combined",
        name="All Major CDNs Combined",
        default_sni="speed.cloudflare.com",
        download_path="/__down?bytes={bytes}",
        description="Consolidated clean edge list covering Cloudflare, AWS CloudFront, Fastly, Google, Azure, and Gcore.",
        endpoints=all_endpoints,
    )


def save_presets_to_directory(target_dir: str | Path = "inputs") -> list[Path]:
    """
    Exports all CDN presets into individual cleanly formatted .txt files inside the designated directory.
    """
    dest = Path(target_dir)
    dest.mkdir(parents=True, exist_ok=True)
    generated_files: list[Path] = []

    file_mapping = [
        ("01_cloudflare_clean_ips.txt", CDN_PRESETS["cloudflare"]),
        ("02_amazon_cloudfront_clean_ips.txt", CDN_PRESETS["cloudfront"]),
        ("03_fastly_clean_ips.txt", CDN_PRESETS["fastly"]),
        ("04_google_cloud_clean_ips.txt", CDN_PRESETS["google"]),
        ("05_microsoft_azure_clean_ips.txt", CDN_PRESETS["azure"]),
        ("06_gcore_clean_ips.txt", CDN_PRESETS["gcore"]),
    ]

    for fname, preset in file_mapping:
        fpath = dest / fname
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {preset.name}\n")
            f.write(f"# Default SNI / Host: {preset.default_sni}\n")
            f.write(f"# Description: {preset.description}\n\n")
            for ep in preset.endpoints:
                f.write(f"{ep}\n")
        generated_files.append(fpath)

    return generated_files


# Pre-compiled CIDR networks for deterministic, offline CDN classification
_CDN_NETWORKS: list[tuple[str, list[ipaddress.IPv4Network | ipaddress.IPv6Network]]] = [
    (
        "Cloudflare",
        [
            ipaddress.ip_network("173.245.48.0/20"),
            ipaddress.ip_network("103.21.244.0/22"),
            ipaddress.ip_network("103.22.200.0/22"),
            ipaddress.ip_network("103.31.4.0/22"),
            ipaddress.ip_network("141.101.64.0/18"),
            ipaddress.ip_network("108.162.192.0/18"),
            ipaddress.ip_network("190.93.240.0/20"),
            ipaddress.ip_network("188.114.96.0/20"),
            ipaddress.ip_network("197.234.240.0/22"),
            ipaddress.ip_network("198.41.128.0/17"),
            ipaddress.ip_network("162.158.0.0/15"),
            ipaddress.ip_network("104.16.0.0/12"),
            ipaddress.ip_network("172.64.0.0/13"),
            ipaddress.ip_network("131.0.72.0/22"),
            ipaddress.ip_network("2400:cb00::/32"),
            ipaddress.ip_network("2606:4700::/32"),
            ipaddress.ip_network("2803:f800::/32"),
            ipaddress.ip_network("2405:b500::/32"),
            ipaddress.ip_network("2405:8100::/32"),
            ipaddress.ip_network("2a06:98c0::/29"),
            ipaddress.ip_network("2c0f:f248::/32"),
        ],
    ),
    (
        "CloudFront",
        [
            ipaddress.ip_network("13.32.0.0/15"),
            ipaddress.ip_network("13.35.0.0/16"),
            ipaddress.ip_network("13.224.0.0/14"),
            ipaddress.ip_network("13.249.0.0/16"),
            ipaddress.ip_network("18.64.0.0/14"),
            ipaddress.ip_network("18.68.0.0/14"),
            ipaddress.ip_network("52.84.0.0/14"),
            ipaddress.ip_network("54.192.0.0/16"),
            ipaddress.ip_network("54.230.0.0/16"),
            ipaddress.ip_network("54.239.128.0/18"),
            ipaddress.ip_network("54.240.128.0/18"),
            ipaddress.ip_network("65.8.0.0/16"),
            ipaddress.ip_network("65.9.0.0/16"),
            ipaddress.ip_network("99.84.0.0/16"),
            ipaddress.ip_network("99.86.0.0/16"),
            ipaddress.ip_network("143.204.0.0/16"),
            ipaddress.ip_network("204.246.160.0/19"),
            ipaddress.ip_network("205.251.192.0/19"),
            ipaddress.ip_network("216.137.32.0/19"),
        ],
    ),
    (
        "Fastly",
        [
            ipaddress.ip_network("151.101.0.0/16"),
            ipaddress.ip_network("199.232.0.0/16"),
            ipaddress.ip_network("146.75.0.0/16"),
            ipaddress.ip_network("2a04:4e40::/32"),
            ipaddress.ip_network("2a04:4e42::/32"),
        ],
    ),
    (
        "Google",
        [
            ipaddress.ip_network("34.96.0.0/11"),
            ipaddress.ip_network("34.128.0.0/10"),
            ipaddress.ip_network("35.184.0.0/13"),
            ipaddress.ip_network("35.192.0.0/12"),
            ipaddress.ip_network("35.208.0.0/12"),
            ipaddress.ip_network("35.224.0.0/12"),
            ipaddress.ip_network("35.240.0.0/13"),
            ipaddress.ip_network("142.250.0.0/15"),
            ipaddress.ip_network("172.217.0.0/16"),
            ipaddress.ip_network("216.58.192.0/19"),
        ],
    ),
    (
        "Azure",
        [
            ipaddress.ip_network("13.107.0.0/16"),
            ipaddress.ip_network("20.150.0.0/16"),
            ipaddress.ip_network("20.184.0.0/13"),
            ipaddress.ip_network("20.190.0.0/15"),
            ipaddress.ip_network("40.90.0.0/15"),
            ipaddress.ip_network("40.126.0.0/18"),
            ipaddress.ip_network("52.160.0.0/11"),
            ipaddress.ip_network("52.178.0.0/16"),
            ipaddress.ip_network("204.79.197.0/24"),
            ipaddress.ip_network("2620:1ec::/40"),
        ],
    ),
    (
        "Gcore",
        [
            ipaddress.ip_network("92.223.64.0/18"),
            ipaddress.ip_network("92.38.128.0/17"),
            ipaddress.ip_network("185.193.0.0/16"),
            ipaddress.ip_network("146.185.200.0/22"),
            ipaddress.ip_network("195.181.160.0/19"),
            ipaddress.ip_network("5.188.118.0/24"),
        ],
    ),
]


def detect_cdn_for_ip(ip_or_host: str, source_hint: str = "") -> str:
    """
    Identifies the CDN provider for an IP literal or hostname using CIDR matching,
    filename source hints, and domain pattern classification.
    """
    hint_lower = source_hint.lower()
    if "cloudflare" in hint_lower:
        return "Cloudflare"
    if "cloudfront" in hint_lower or "amazon" in hint_lower or "aws" in hint_lower:
        return "CloudFront"
    if "fastly" in hint_lower:
        return "Fastly"
    if "google" in hint_lower or "gcp" in hint_lower:
        return "Google"
    if "azure" in hint_lower or "microsoft" in hint_lower:
        return "Azure"
    if "gcore" in hint_lower:
        return "Gcore"

    cleaned = ip_or_host.strip().strip("[]")
    if not cleaned:
        return "Custom"

    # Try raw IP subnet matching
    try:
        ip = ipaddress.ip_address(cleaned)
        for provider_name, net_list in _CDN_NETWORKS:
            for net in net_list:
                if ip in net:
                    return provider_name
    except ValueError:
        pass

    # Hostname pattern matching
    h_lower = cleaned.lower()
    if "cloudflare" in h_lower:
        return "Cloudflare"
    if "cloudfront" in h_lower:
        return "CloudFront"
    if "fastly" in h_lower:
        return "Fastly"
    if "google" in h_lower or "1e100.net" in h_lower:
        return "Google"
    if "azure" in h_lower or "trafficmanager.net" in h_lower:
        return "Azure"
    if "gcore" in h_lower:
        return "Gcore"

    return "Custom"

