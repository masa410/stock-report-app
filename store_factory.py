"""認証情報から保存先を作る。GitHub Actions（環境変数）・Streamlit（st.secrets）・PC（.streamlit/secrets.toml）に対応。"""
import json
import os

from store import SheetsStore

HERE = os.path.dirname(os.path.abspath(__file__))


def from_env():
    raw = os.environ.get("GCP_SA_JSON")
    sid = os.environ.get("SPREADSHEET_ID")
    if raw and sid:
        return SheetsStore(json.loads(raw), sid)
    return None


def from_secrets_file(path=None):
    path = path or os.path.join(HERE, ".streamlit", "secrets.toml")
    if not os.path.exists(path):
        return None
    import toml
    d = toml.load(path)
    return SheetsStore(dict(d["gcp_service_account"]), d["spreadsheet_id"])


def from_streamlit_secrets(secrets):
    return SheetsStore(dict(secrets["gcp_service_account"]), secrets["spreadsheet_id"])


def get_store():
    s = from_env() or from_secrets_file()
    if s is None:
        raise RuntimeError("認証情報が見つかりません（環境変数 GCP_SA_JSON / SPREADSHEET_ID、または .streamlit/secrets.toml）")
    return s
