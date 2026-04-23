.PHONY: help install serve clean

help:           ## show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?##"}; {printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

install:        ## install python package (editable) + web deps + frontend bundle
	pip install -e ./core
	cd core/web && npm install && npm run build

serve:          ## start API + Web UI + compile watcher (runs against ./my-wiki)
	cd my-wiki && zenwiki serve

clean:          ## wipe local caches (search db, preflight, audit log, pycache)
	rm -rf my-wiki/.zenwiki/search.db my-wiki/.zenwiki/search.db-shm my-wiki/.zenwiki/search.db-wal
	rm -f my-wiki/.zenwiki/preflight.json my-wiki/.zenwiki/dedup-audit.jsonl
	find . -type d -name __pycache__ -exec rm -rf {} +
