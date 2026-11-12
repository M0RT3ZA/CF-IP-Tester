from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

CLOUDFLARE_META_URL = "https://speed.cloudflare.com/meta"
IP_API_URL = "http://ip-api.com/json"

# Common VPN, Proxy, and Datacenter hosting ASNs and organizational keywords.
# When benchmarking endpoints, the user should test on their raw ISP network interface
# rather than through an active VPN/Tunnel tunnel interface.
VPN_DATACENTER_KEYWORDS = (
    "vpn", "proxy", "datacenter", "hosting", "cloud", "server", "vps",
    "mullvad", "nordvpn", "expressvpn", "surfshark", "proton", "wireguard",
    "hetzner", "ovh", "digitalocean", "linode", "vultr", "aws", "amazon",
    "google cloud", "microsoft azure", "oracle", "leaseweb", "contabo",
)


class IspDetector:
    """
    Resolves client ASN, ISP, and geographic metadata via public lookup endpoints.
    Employs fallback redundancy to ensure reliable detection under restrictive egress policies.
    """

    @classmethod
    def detect_current_isp(cls, timeout_s: float = 4.0) -> dict[str, Any]:
        result = cls._query_cloudflare_meta(timeout_s)
        if result.get("isp") and result.get("isp") != "Unknown":
            result["is_vpn_or_dc"] = cls.is_vpn_or_datacenter(result.get("org", "") or result.get("isp", ""))
            return result

        fallback = cls._query_ip_api(timeout_s)
        if fallback.get("isp") and fallback.get("isp") != "Unknown":
            fallback["is_vpn_or_dc"] = cls.is_vpn_or_datacenter(fallback.get("org", "") or fallback.get("isp", ""))
            return fallback

        return {
            "isp": "Unknown",
            "org": "Unknown",
            "asn": "",
            "ip": "",
            "country": "",
            "city": "",
            "is_vpn_or_dc": False,
        }

    @classmethod
    def is_vpn_or_datacenter(cls, org_or_isp: str) -> bool:
        lower = org_or_isp.lower()
        return any(kw in lower for kw in VPN_DATACENTER_KEYWORDS)

    @staticmethod
    def _query_cloudflare_meta(timeout_s: float) -> dict[str, Any]:
        req = urllib.request.Request(
            CLOUDFLARE_META_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    as_org = payload.get("asOrganization") or payload.get("isp") or ""
                    cleaned_name = IspDetector._clean_operator_name(as_org)
                    return {
                        "isp": cleaned_name,
                        "org": as_org,
                        "asn": str(payload.get("asn", "")),
                        "ip": payload.get("clientIp", ""),
                        "country": payload.get("country", ""),
                        "city": payload.get("city", ""),
                    }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass

        return {}

    @staticmethod
    def _query_ip_api(timeout_s: float) -> dict[str, Any]:
        req = urllib.request.Request(
            IP_API_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    isp = payload.get("isp") or payload.get("org") or ""
                    cleaned_name = IspDetector._clean_operator_name(isp)
                    return {
                        "isp": cleaned_name,
                        "org": isp,
                        "asn": payload.get("as", ""),
                        "ip": payload.get("query", ""),
                        "country": payload.get("country", ""),
                        "city": payload.get("city", ""),
                    }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass

        return {}

    @staticmethod
    def _clean_operator_name(raw_name: str) -> str:
        """
        Normalizes verbose telecommunication entity names into concise operator identifiers.
        """
        lower = raw_name.lower()
        if "irancell" in lower or "mtnirancell" in lower:
            return "Irancell"
        if "mobile telecommunication company of iran" in lower or "mci" in lower or "hamrah-e-avval" in lower:
            return "MCI"
        if "shatel" in lower or "aria shatel" in lower:
            return "Shatel"
        if "telecommunication company of iran" in lower or "tci" in lower or "mokhaberat" in lower:
            return "TCI"
        if "asiatech" in lower:
            return "Asiatech"
        if "rightel" in lower:
            return "Rightel"
        if "mobinnet" in lower:
            return "Mobinnet"
        if "hiweb" in lower or "dadeh gostar" in lower:
            return "HiWeb"
        if "pars online" in lower:
            return "ParsOnline"
        if "pishgaman" in lower:
            return "Pishgaman"
        if "afranet" in lower:
            return "Afranet"
        if "cloudflare" in lower:
            return "Cloudflare"

        # If unmapped, sanitize punctuation and return title-cased representation
        sanitized = "".join(ch for ch in raw_name if ch.isalnum() or ch in " -_").strip()
        return sanitized if sanitized else "Unknown"
