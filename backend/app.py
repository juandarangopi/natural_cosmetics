import hashlib
import hmac
import json
import os

import httpx
from flask import Flask, jsonify, redirect, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=os.getenv("ALLOWED_ORIGINS", "*"))

LS_API_KEY = os.getenv("LEMONSQUEEZY_API_KEY", "")
LS_STORE_ID = os.getenv("LEMONSQUEEZY_STORE_ID", "")
LS_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
LS_CHECKOUT_URL = os.getenv("LS_CHECKOUT_URL", "")
LS_VARIANT_ID = os.getenv("LS_VARIANT_ID", "")
LS_API_BASE = "https://api.lemonsqueezy.com/v1"


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/config")
def get_config():
    return jsonify({
        "lsCheckoutUrl": LS_CHECKOUT_URL,
        "lsVariantId": LS_VARIANT_ID,
    })


@app.route("/products", methods=["GET"])
def get_products():
    if not LS_API_KEY or not LS_STORE_ID:
        return jsonify({"error": "Lemon Squeezy credentials not configured"}), 500

    headers = {
        "Authorization": f"Bearer {LS_API_KEY}",
        "Accept": "application/vnd.api+json",
    }

    try:
        resp = httpx.get(
            f"{LS_API_BASE}/products",
            params={"filter[store_id]": LS_STORE_ID, "include": "variants"},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Lemon Squeezy error: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/product-cover", methods=["GET"])
def get_product_cover():
    if not LS_API_KEY:
        return jsonify({"error": "Lemon Squeezy API key not configured"}), 500

    headers = {
        "Authorization": f"Bearer {LS_API_KEY}",
        "Accept": "application/vnd.api+json",
    }

    # Prefer variant ID (always correct) over store ID filter
    if LS_VARIANT_ID:
        try:
            resp = httpx.get(
                f"{LS_API_BASE}/variants/{LS_VARIANT_ID}",
                params={"include": "product"},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            included = data.get("included", [])
            product = next((item for item in included if item.get("type") == "products"), None)
            if product:
                attrs = product["attributes"]
                return jsonify({
                    "name": attrs.get("name"),
                    "cover_url": attrs.get("large_thumb_url") or attrs.get("thumb_url"),
                })
        except httpx.HTTPStatusError as e:
            return jsonify({"error": f"Lemon Squeezy error: {e.response.text}"}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Fallback: filter by store_id
    if not LS_STORE_ID:
        return jsonify({"error": "Configure LS_VARIANT_ID or LEMONSQUEEZY_STORE_ID"}), 500

    try:
        resp = httpx.get(
            f"{LS_API_BASE}/products",
            params={"filter[store_id]": LS_STORE_ID, "page[size]": 1},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        products = resp.json().get("data", [])
        if not products:
            return jsonify({"error": "No products found"}), 404

        attrs = products[0]["attributes"]
        return jsonify({
            "name": attrs.get("name"),
            "cover_url": attrs.get("large_thumb_url") or attrs.get("thumb_url"),
        })
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Lemon Squeezy error: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/create-checkout", methods=["POST"])
def create_checkout():
    if not LS_API_KEY or not LS_STORE_ID:
        return jsonify({"error": "Lemon Squeezy credentials not configured"}), 500

    data = request.get_json(force=True) or {}
    variant_id = data.get("variantId", "")
    success_url = data.get("successUrl", "")

    if not variant_id:
        return jsonify({"error": "Missing variantId"}), 400
    if not success_url:
        return jsonify({"error": "Missing successUrl"}), 400

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_options": {
                    "embed": False,
                    "media": True,
                    "logo": True,
                },
                "checkout_data": {},
                "product_options": {
                    "redirect_url": success_url,
                },
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": str(LS_STORE_ID)}},
                "variant": {"data": {"type": "variants", "id": str(variant_id)}},
            },
        }
    }

    headers = {
        "Authorization": f"Bearer {LS_API_KEY}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }

    try:
        resp = httpx.post(f"{LS_API_BASE}/checkouts", json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        checkout_url = resp.json()["data"]["attributes"]["url"]
        return jsonify({"url": checkout_url})
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Lemon Squeezy error: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


LS_LICENSE_API = "https://api.lemonsqueezy.com/v1/licenses/validate"


@app.route("/verify-license", methods=["POST"])
def verify_license():
    data = request.get_json(force=True) or {}
    license_key = data.get("license_key", "").strip()

    if not license_key:
        return jsonify({"valid": False, "error": "Debes ingresar una clave de licencia"}), 400

    try:
        resp = httpx.post(
            LS_LICENSE_API,
            data={"license_key": license_key},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        ls_data = resp.json()

        if not ls_data.get("valid"):
            error_msg = ls_data.get("error") or "Licencia inválida o no encontrada"
            return jsonify({"valid": False, "error": error_msg}), 403

        meta = ls_data.get("meta", {})
        return jsonify({
            "valid": True,
            "customer_name": meta.get("customer_name", ""),
            "customer_email": meta.get("customer_email", ""),
            "product_name": meta.get("product_name", ""),
        })
    except httpx.TimeoutException:
        return jsonify({"valid": False, "error": "Tiempo de espera agotado, intenta de nuevo"}), 504
    except Exception:
        return jsonify({"valid": False, "error": "Error al verificar la licencia"}), 500


def _validate_license_get_variant(license_key):
    """Validate a license key and return variant_id, or raise on failure."""
    resp = httpx.post(
        LS_LICENSE_API,
        data={"license_key": license_key},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    ls_data = resp.json()
    if not ls_data.get("valid"):
        return None, ls_data.get("error") or "Licencia inválida"
    variant_id = ls_data.get("meta", {}).get("variant_id")
    return variant_id, None


def _fetch_variant_files(variant_id):
    """Return the list of file objects for a variant from Lemon Squeezy."""
    ls_headers = {
        "Authorization": f"Bearer {LS_API_KEY}",
        "Accept": "application/vnd.api+json",
    }
    files_resp = httpx.get(
        f"{LS_API_BASE}/files",
        params={"filter[variant_id]": variant_id},
        headers=ls_headers,
        timeout=15,
    )
    files_resp.raise_for_status()
    return files_resp.json().get("data", [])


@app.route("/ebook-files", methods=["GET"])
def list_ebook_files():
    """Return metadata for all downloadable files associated with a license."""
    license_key = request.args.get("license_key", "").strip()

    if not license_key:
        return jsonify({"error": "Se requiere una clave de licencia"}), 400
    if not LS_API_KEY:
        return jsonify({"error": "API key no configurada en el servidor"}), 500

    try:
        variant_id, err = _validate_license_get_variant(license_key)
    except httpx.TimeoutException:
        return jsonify({"error": "Tiempo de espera agotado, intenta de nuevo"}), 504
    except Exception:
        return jsonify({"error": "Error al verificar la licencia"}), 500

    if err:
        return jsonify({"error": err}), 403
    if not variant_id:
        return jsonify({"error": "No se pudo determinar el producto asociado"}), 500

    try:
        files = _fetch_variant_files(variant_id)
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Error al obtener los archivos: {e.response.status_code}"}), 502
    except Exception:
        return jsonify({"error": "Error al obtener los archivos"}), 500

    if not files:
        return jsonify({"error": "No hay archivos disponibles para este producto"}), 404

    file_list = [
        {
            "id": f["id"],
            "name": f["attributes"].get("name", f"Ebook {i + 1}"),
            "size": f["attributes"].get("size"),
        }
        for i, f in enumerate(files)
    ]
    return jsonify({"files": file_list})


@app.route("/download-ebook", methods=["GET"])
def download_ebook():
    license_key = request.args.get("license_key", "").strip()
    file_id = request.args.get("file_id", "").strip()

    if not license_key:
        return jsonify({"error": "Se requiere una clave de licencia"}), 400

    if not LS_API_KEY:
        return jsonify({"error": "API key no configurada en el servidor"}), 500

    # Step 1: Validate license and extract variant_id
    try:
        variant_id, err = _validate_license_get_variant(license_key)
    except httpx.TimeoutException:
        return jsonify({"error": "Tiempo de espera agotado, intenta de nuevo"}), 504
    except Exception:
        return jsonify({"error": "Error al verificar la licencia"}), 500

    if err:
        return jsonify({"error": err}), 403
    if not variant_id:
        return jsonify({"error": "No se pudo determinar el producto asociado"}), 500

    # Step 2: Fetch files for this variant from Lemon Squeezy
    try:
        files = _fetch_variant_files(variant_id)
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Error al obtener el archivo de Lemon Squeezy: {e.response.status_code}"}), 502
    except Exception:
        return jsonify({"error": "Error al obtener el archivo"}), 500

    if not files:
        return jsonify({"error": "No hay archivos disponibles para este producto"}), 404

    # Select the requested file by id, by index, or fall back to the first one
    file_index_raw = request.args.get("file_index", "").strip()
    if file_id:
        file_data = next((f for f in files if str(f["id"]) == file_id), None)
        if not file_data:
            return jsonify({"error": "Archivo no encontrado"}), 404
    elif file_index_raw.isdigit():
        idx = int(file_index_raw)
        if idx >= len(files):
            return jsonify({"error": "Índice de archivo fuera de rango"}), 404
        file_data = files[idx]
    else:
        file_data = files[0]

    download_url = file_data["attributes"].get("download_url")

    if not download_url:
        return jsonify({"error": "URL de descarga no disponible"}), 503

    # Step 3: Redirect the browser directly to the LS/S3 pre-signed URL.
    # Server-to-server proxying fails because S3 pre-signed URLs have very short
    # TTLs and origin restrictions. The redirect is safe: the URL is time-limited
    # and only issued after the license has been validated above.
    return redirect(download_url, code=302)


@app.route("/webhook", methods=["POST"])
def lemonsqueezy_webhook():
    if not LS_WEBHOOK_SECRET:
        return jsonify({"error": "Webhook secret not configured"}), 500

    signature = request.headers.get("X-Signature", "")
    payload = request.data

    expected = hmac.new(
        LS_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return jsonify({"error": "Invalid signature"}), 400

    event = json.loads(payload)
    event_name = event.get("meta", {}).get("event_name", "")

    if event_name == "order_created":
        order = event.get("data", {})
        print(f"New order received: {order.get('id')} — status: {order.get('attributes', {}).get('status')}")
        # Add post-payment logic here (send email, grant access, etc.)

    return jsonify({"received": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
