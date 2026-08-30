# Интеграция админки бота с панелью RIXXX

Если мы ставим бота на новый сервер с панелью RIXXX, нам нужно, чтобы Caddy проксировал админку бота (порт 1488).

Для этого на сервере с установленной панелью RIXXX выполняем команду:

```bash
cat << 'HOOK' >> /opt/panel-naive-mieru/server/caddyTemplate.js

const _origRender = module.exports.render;
module.exports.render = function(cfg, users) {
    return _origRender(cfg, users) + "\n\nтвой_домен_для_бота.ru {\n  reverse_proxy 127.0.0.1:1488\n}\n";
};
HOOK

После этого пересобираем конфиг панели: bash /opt/panel-naive-mieru/update.sh --repair -y
