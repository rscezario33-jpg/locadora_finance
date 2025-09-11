# utils_cep.py
import requests

def busca_cep(cep: str) -> dict | None:
    cep = ''.join(filter(str.isdigit, cep or ""))[:8]
    if len(cep) != 8:
        return None
    r = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=10)
    if r.ok:
        j = r.json()
        if j.get("erro"):
            return None
        return {
            "cep": j.get("cep",""),
            "logradouro": j.get("logradouro",""),
            "complemento": j.get("complemento",""),
            "bairro": j.get("bairro",""),
            "cidade": j.get("localidade",""),
            "estado": j.get("uf",""),
        }
    return None
