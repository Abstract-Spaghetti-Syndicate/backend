import socket
import asyncio

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_subnet_ips(local_ip: str) -> list:
    if not local_ip or local_ip == "127.0.0.1":
        return []
    parts = local_ip.split(".")
    if len(parts) != 4:
        return []
    prefix = f"{parts[0]}.{parts[1]}.{parts[2]}."
    return [f"{prefix}{i}" for i in range(1, 255) if f"{prefix}{i}" != local_ip]

async def try_tcp_connect(ip: str, port: int, timeout: float = 0.3) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def scan_network_for_printers_tcp() -> list:
    local_ip = get_local_ip()
    ips = get_subnet_ips(local_ip)
    if not ips:
        print("[TCP SCAN] Не вдалося знайти локальний інтерфейс для сканування.", flush=True)
        return []
        
    print(f"[TCP SCAN] Початок сканування підмережі {local_ip} для портів 7125 та 5000...", flush=True)
    
    tasks_klipper = [try_tcp_connect(ip, 7125) for ip in ips]
    tasks_octo = [try_tcp_connect(ip, 5000) for ip in ips]
    
    results_klipper = await asyncio.gather(*tasks_klipper)
    results_octo = await asyncio.gather(*tasks_octo)
    
    found_printers = []
    for i, ip in enumerate(ips):
        if results_klipper[i]:
            found_printers.append({
                "name": f"Klipper ({ip})",
                "type": "klipper",
                "ip": ip,
                "port": 7125
            })
        if results_octo[i]:
            found_printers.append({
                "name": f"OctoPrint ({ip})",
                "type": "octoprint",
                "ip": ip,
                "port": 5000
            })
            
    print(f"[TCP SCAN] Сканування завершено. Знайдено: {len(found_printers)} пристроїв.", flush=True)
    return found_printers