# CF IP Tester

[Persian Documentation / نسخه فارسی](README.md)

Production-grade, cross-platform desktop benchmark suite designed to evaluate Cloudflare clean IPs (IPv4 and IPv6) and proxy domains across multiple Internet Service Providers (ISPs).

Universally compatible with all proxy management panels and client configurations, including X-UI, Marzban, Hiddify, Sing-box, V2Ray, Clash, and deployments on Cloudflare Workers and Pages.

---

## Architectural Principles

### 1. Application-Layer Edge Benchmark vs. Raw ICMP/TCP Probing
Simple ICMP ping or raw TCP handshakes fail to reflect real-world Cloudflare performance under Deep Packet Inspection (DPI) environments. Many edge IP addresses acknowledge TCP SYN packets instantly but throttle or terminate TLS payload streams.

`CF IP Tester` establishes raw TLS/SNI socket wrapping directly to port 443 of the target IP, injecting `speed.cloudflare.com` as the Server Name Indication (SNI) and HTTP `Host` header. This precisely mirrors how VLESS and Trojan proxy clients route traffic through clean Cloudflare IPs. Test payloads are streamed directly into volatile memory without disk I/O, computing exact megabits-per-second (Mbps) throughput while discarding responses under 50 KB to filter captive portals and ISP block pages.

### 2. Multi-Operator Cross-ISP Intersection & Harmonic Mean Scoring
Network paths vary significantly between telecom operators (e.g., Irancell, MCI, Shatel, TCI). An IP achieving 100 Mbps on one operator may be throttled or blocked on another.

- **Coverage Factor**: Quadratic weighting guarantees that endpoints accessible on 100% of tested networks rank at the top of the comparison matrix.
- **Harmonic Mean Throughput**: In distributed systems, arithmetic means produce overly optimistic figures when an endpoint suffers severe degradation on one link. The harmonic mean strongly penalizes near-zero throughput outliers, selecting endpoints with consistent reliability across all tested networks.

### 3. Real Egress Location Discovery via Anycast PoP Analysis
Because CDNs like Cloudflare utilize Anycast routing globally, conventional Whois and IP geolocation databases display misleading corporate headquarters information (e.g., San Francisco, CA) rather than the physical egress data center processing your traffic.
- `CF IP Tester` deterministically parses the 3-letter IATA airport code (e.g., `FRA`, `AMS`, `IST`, `DXB`) from the edge response headers (`cf-ray` and edge response metadata) and resolves it entirely offline to its actual City, Country, and PoP identifier (e.g., `Frankfurt, DE [FRA]`, `Istanbul, TR [IST]`, `Amsterdam, NL [AMS]`, `Dubai, AE [DXB]`).
- Displayed across both the Live Test table and Cross-ISP Matrix in a dedicated **Location** column, and fully persisted in all exports (`.txt`, `.csv`, `.xlsx`, `.xls`, `.sqlite`).

### 4. Application-Layer Service Auditing & Fitness Multiplier
Edge IPs may exhibit high bandwidth while egressing through Cloudflare data centers that are rate-limited or blocked by services like YouTube (bot challenges / HTTP 429) or Instagram/X (IP reputation blacklists).
- When **Audit Services (TG/YT/IG/X)** is enabled, the benchmark runs lightweight, non-blocking probes after speed testing:
  1. **Telegram (TG)**: Verifies gateway reachability to `api.telegram.org`.
  2. **YouTube (YT)**: Sub-second `GET /generate_204` check on `www.youtube.com` confirming zero captchas or 429 errors.
  3. **Instagram (IG)**: Checks handshake and web fronting headers on `www.instagram.com`.
  4. **X / Twitter (X)**: Validates public guest token activation gateway on `api.twitter.com`.
- A **Service Fitness Multiplier** (0.40x to 1.25x) scales the Universal Score, enabling sorting by **Target Services Viability** to identify universally unlocked endpoints.

### 5. Automated Pre-Flight ISP Check & VPN Guard
To prevent inaccurate benchmark runs caused by unrecognized network hops:
- When **Start Benchmark** is clicked, the suite immediately probes the active default network route, discovers the actual local ISP and ASN in real time, and updates the operator field.
- If an active VPN tunnel, datacenter IP, or proxy routing interface is detected on the local system, an actionable warning dialog is displayed to advise the user to disconnect third-party VPNs before measuring raw ISP performance.

---

## Multi-CDN Provider Support & Curated Presets

The suite features built-in curated edge presets accessible via the **CDN Presets ▼** button:

1. **Cloudflare (IPv4 & IPv6)**: Anycast clean edges and IPv6 blocks (default SNI: `speed.cloudflare.com`).
2. **Amazon CloudFront (AWS)**: Global edge locations across Europe, Middle East, and Asia (default SNI: `aws.amazon.com`).
3. **Fastly CDN**: Fastly edge anycast clusters (default SNI: `www.fastly.com`).
4. **Google Cloud CDN / Google Edge**: Google edge front-end infrastructure (default SNI: `cloud.google.com`).
5. **Microsoft Azure / Azure Front Door**: Microsoft edge PoPs and Front Door endpoints (default SNI: `edge.microsoft.com`).
6. **Gcore CDN**: Global edge nodes with extensive regional coverage (default SNI: `gcore.com`).
7. **All Major CDNs Combined**: Comprehensive consolidated multi-provider benchmark list.

The configurable **SNI / Host** field allows users to test with provider defaults or enter their own custom Workers/Pages/CloudFront/Fastly proxy domain. Selecting *Export All Presets into inputs/ Directory* outputs organized `.txt` files directly into `./inputs/`.

---

## Supported Input Formats

The application provides automated directory scanning (`inputs/`) and interactive manual file loading:

- **Plain Text (`.txt`)**: One IPv4, IPv6, or domain name per line (supports `#` inline comments).
- **Modern Spreadsheets (`.xlsx`)**: High-throughput parsing via `openpyxl`.
- **Legacy Spreadsheets (`.xls`)**: Binary BIFF8 workbook parsing via `xlrd`.
- **Delimited Data (`.csv`)**: Automatic column detection for host and IP targets.
- **Relational Databases (`.sqlite`, `.db`)**: Automatic table and column discovery.

---

## Supported Export Formats & CDN/Location Reporting

All UI tables and export targets include explicit CDN provider and physical egress location tracking:
- **Live Test Table**: Displays dedicated "CDN" and "Location" (PoP airport code and city/country) columns alongside Resolved IP, Operator, Ping, Speed, Jitter, Loss, and Services viability.
- **Cross-ISP Summary Matrix**: Features dedicated "CDN" and "Location" columns alongside Coverage, Min Speed, Harmonic Mean, and Universal Score.
- **Clean Proxy Panel List (`.txt`)**: Deduplicated list of winning endpoints with inline provider comments and location tags (`# CDN (Location)`) for direct import into proxy panels (X-UI, Marzban, Hiddify, Sing-box).
- **Excel Report Workbook (`.xlsx`)**: Multi-sheet workbook with raw operator results and the consolidated Cross-ISP Summary matrix, both containing the "CDN" and "Location" columns.
- **Legacy Excel (`.xls`)**: Formatted BIFF8 spreadsheet via `xlwt` with CDN and Location metadata.
- **Comma-Separated Values (`.csv`)**: Structured export with `cdn` and `location` columns for raw runs and matrix benchmarks.
- **Relational Database (`.sqlite`)**: Clean relational export of `endpoint_results` and `cross_isp_summary` tables containing the `cdn` and `location` text columns.
- **Automatic Subnet/CIDR Classifier**: Custom or manually added IPs are automatically mapped to their origin CDN (Cloudflare, CloudFront, Fastly, Google, Azure, Gcore) via offline pre-compiled CIDR matching.

---

## Quick Setup & Execution Scripts

Automated launcher scripts are provided for each operating system. They inspect Python prerequisites, configure the virtual environment, install missing packages from `requirements.txt`, and provide an interactive choice to run the GUI or compile a standalone binary:

### Windows
Double-click `run.bat` or execute in Command Prompt:
```cmd
run.bat
```
Or for PowerShell users:
```powershell
.\run.ps1
```

### Linux
Grant executable permissions and run:
```bash
chmod +x run.sh
./run.sh
```

### macOS
Double-click `run_macos.command` in Finder or run in Terminal:
```bash
chmod +x run_macos.command
./run_macos.command
```

---

## Interactive Launcher Menu & Persistent Loop

Launchers run in a persistent loop; closing the GUI or finishing binary compilation automatically returns you to the main menu without terminating the console session:
- **Option 1 (Launch GUI - Default)**: Starts the PySide6 desktop interface directly. Closing the window returns to this menu.
- **Option 2 (Build Standalone Binary)**: Installs PyInstaller, compiles a single-file executable in `dist/`, and reveals it in the file manager.
- **Option 0 (Exit)**: Exits the launcher and closes the console window. (Option 3 is also accepted for backward compatibility).

---

## Manual Execution via Python

If you prefer running directly without the launcher scripts:

```bash
# Create and activate virtual environment
python -m venv .venv

# On Windows:
.\.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

---

## Standalone Binary Packaging (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "CF-IP-Tester" --clean main.py
```
The compiled executable will be located in the `dist/` folder.

---

## Directory Structure

```text
Ip Scanner/
├── inputs/
│   ├── sample_targets.txt        # Target input text file (empty template for custom IPs/domains)
│   ├── 01_cloudflare_clean_ips.txt
│   ├── 02_amazon_cloudfront_clean_ips.txt
│   ├── 03_fastly_clean_ips.txt
│   ├── 04_google_cloud_clean_ips.txt
│   ├── 05_microsoft_azure_clean_ips.txt
│   └── 06_gcore_clean_ips.txt
├── data/
│   └── .gitkeep                  # Local SQLite database directory for multi-session data
├── src/
│   ├── __init__.py
│   ├── models.py                 # Dataclasses and type models
│   ├── core/
│   │   ├── __init__.py
│   │   ├── prober.py             # Low-level TLS/SNI socket prober & volatile stream engine
│   │   ├── service_auditor.py    # Service reachability auditor & IATA PoP location resolver
│   │   ├── cdn_presets.py        # Curated IP ranges, endpoints, and CIDR subnet classifier
│   │   ├── isp_detector.py       # ASN and ISP discovery resolver
│   │   └── aggregator.py         # Multi-ISP intersection and harmonic scoring engine
│   ├── io/
│   │   ├── __init__.py
│   │   ├── loader.py             # Multi-format ingestion and deduplication
│   │   └── exporter.py           # Multi-format exporter (TXT, CSV, XLS, XLSX, SQLite)
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py        # PySide6 desktop GUI interface
│       └── workers.py            # Non-blocking QThread worker pool
├── main.py                       # Main application entry point
├── run.bat                       # Automated setup and launcher for Windows
├── run.ps1                       # Automated setup and launcher for Windows PowerShell
├── run.sh                        # Automated setup and launcher for Linux
├── run_macos.command             # Double-clickable launcher for macOS
├── requirements.txt              # Pinned dependencies
├── .gitignore                    # Git ignore specifications
├── README.md                     # Persian Documentation (Default)
└── README_EN.md                  # English Documentation
```
