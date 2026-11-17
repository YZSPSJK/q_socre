import os
import tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener

from django.core.exceptions import ImproperlyConfigured


def load_config(base_dir):
    if server := os.getenv("QSCORE_NACOS_URL"):
        return load_nacos_config(server)
    override = os.getenv("QSCORE_CONFIG")
    config_path = Path(override) if override else base_dir / "qscore.local.toml"
    if override or config_path.is_file():
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)
    return {}


def load_nacos_config(server):
    import yaml

    server = server.rstrip("/")
    location = urlsplit(server)
    if location.scheme not in {"http", "https"} or not location.hostname or (
        location.username or location.password or location.query or location.fragment or location.path
    ):
        raise ImproperlyConfigured("QSCORE_NACOS_URL 请填写 Nacos 的 HTTP 或 HTTPS 地址，不含账号或路径。")

    params = {
        "dataId": os.getenv("QSCORE_NACOS_DATA_ID", "simtek_qscore.yaml"),
        "group": os.getenv("QSCORE_NACOS_GROUP", "DEFAULT_GROUP"),
    }
    if namespace := os.getenv("QSCORE_NACOS_NAMESPACE"):
        params["tenant"] = namespace
    url = f"{server}/nacos/v1/cs/configs?{urlencode(params)}"
    http = build_opener(ProxyHandler({}))
    try:
        with http.open(url, timeout=5) as response:
            content = response.read(65537)
    except HTTPError as error:
        raise ImproperlyConfigured(f"读取 Nacos 配置失败（HTTP {error.code}）。") from None
    except (URLError, TimeoutError):
        raise ImproperlyConfigured("无法连接 Nacos 配置服务，请检查地址和网络。") from None
    if len(content) > 65536:
        raise ImproperlyConfigured("Nacos 的 QScore 配置超过 64 KiB。")
    try:
        config = yaml.safe_load(content)
    except yaml.YAMLError:
        raise ImproperlyConfigured("Nacos 的 QScore 配置不是有效的 YAML。") from None
    if not isinstance(config, dict) or not isinstance(config.get("database"), dict):
        raise ImproperlyConfigured("Nacos 配置缺少 database，请配置 host、port、name 和 user。")
    database = config["database"]
    port = database.get("port")
    for field in ("host", "name", "user"):
        if not isinstance(database.get(field), str) or not database[field].strip():
            raise ImproperlyConfigured(f"Nacos 配置中的 database.{field} 必须是非空字符串。")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ImproperlyConfigured("Nacos 配置中的 database.port 必须是有效的整数端口。")
    app = config.get("app", {})
    if not isinstance(app, dict) or ("debug" in app and type(app["debug"]) is not bool):
        raise ImproperlyConfigured("Nacos 配置中的 app.debug 必须为 true 或 false。")
    for name in ("QSCORE_SECRET_KEY", "QSCORE_DB_PASSWORD"):
        if not os.getenv(name):
            raise ImproperlyConfigured(f"Nacos 模式需要通过环境变量提供 {name}。")
    return {
        "app": {"debug": app.get("debug", False)},
        "database": {field: database[field] for field in ("host", "port", "name", "user")},
    }
