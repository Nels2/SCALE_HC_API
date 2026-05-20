import os
import scale_session

host = os.getenv("SC_HOST", "").rstrip("/")
url = f"{host}/rest/v1/VirDomainStats"

resp = scale_session.get(url)

print("HTTP:", resp.status_code)
print(resp.text[:500])