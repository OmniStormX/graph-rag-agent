NEO4J_SERVICE ?= neo4j
NEO4J_USER ?= neo4j
NEO4J_PASSWORD ?= 12345678
FORCE ?= 0
ADMIN_BACKEND_PORT ?= 8001

.PHONY: clean-neo4j clean-cache reset-graph verify-neo4j rebuild-graph start-backend start-frontend start-admin-frontend start-admin-backend help-admin

clean-cache:
	@echo "清空本地缓存目录..."
	@rm -rf cache
	@echo "本地缓存目录已清空。"

clean-neo4j:
	@echo "清空 Neo4j 图数据..."
	@docker compose exec -T $(NEO4J_SERVICE) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "MATCH (n) DETACH DELETE n;"
	@echo "尝试删除 Neo4j 向量索引..."
	@docker compose exec -T $(NEO4J_SERVICE) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "DROP INDEX entity_embedding IF EXISTS;"
	@docker compose exec -T $(NEO4J_SERVICE) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "DROP INDEX chunk_embedding IF EXISTS;"
	@docker compose exec -T $(NEO4J_SERVICE) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "DROP INDEX vector IF EXISTS;"
	@echo "Neo4j 图数据已清空。"

reset-graph:
	@if [ "$(FORCE)" != "1" ]; then \
		echo "该操作会清空 Neo4j 图数据和本地 cache/ 缓存。"; \
		echo "如确认执行，请使用: make reset-graph FORCE=1"; \
		exit 1; \
	fi
	@$(MAKE) clean-neo4j
	@$(MAKE) clean-cache
	@echo "图数据与本地缓存已全部清空。"

verify-neo4j:
	@echo "检查 Neo4j 当前节点数量..."
	@docker compose exec -T $(NEO4J_SERVICE) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "MATCH (n) RETURN count(n) AS node_count;"

rebuild-graph: clean-neo4j
	@echo "开始执行全量图谱重建..."
	@python -m graphrag_agent.integrations.build.main
	@echo "全量图谱重建完成。"

start-backend:
	@echo "启动 FastAPI 后端..."
	@cd server && PYTHONPATH=.. python -m uvicorn main:app --reload --port 8000

start-frontend:
	@echo "启动 Streamlit 前端..."
	@cd frontend && PYTHONPATH=.. streamlit run app.py --server.fileWatcherType none

start-admin-backend:
	@echo "启动 Admin FastAPI 后端，监听端口 $(ADMIN_BACKEND_PORT)..."
	@cd server && PYTHONPATH=.. python -m uvicorn main:app --reload --port $(ADMIN_BACKEND_PORT)

start-admin-frontend:
	@echo "启动 Admin Streamlit 前端..."
	@cd frontend && ADMIN_FRONTEND_API_URL=http://127.0.0.1:$(ADMIN_BACKEND_PORT) PYTHONPATH=.. streamlit run admin_app.py --server.fileWatcherType none

help-admin:
	@echo "后台管理系统启动说明："
	@echo "1. 确保 .env 中 GRAPH_ADMIN_ENABLED=true"
	@echo "2. 确保 PostgreSQL 已启动且 GRAPH_ADMIN_METADATA_DSN 可用"
	@echo "3. 启动后端: make start-admin-backend"
	@echo "4. 启动前端: make start-admin-frontend"
	@echo "5. 当前默认后台端口: $(ADMIN_BACKEND_PORT)"
