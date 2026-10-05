.PHONY: up verify down test-backend test-frontend e2e

up:        ## 构建并后台启动全部服务
	docker compose up --build -d

verify:    ## 运行一次性验收服务（退出码即结果）
	docker compose run --rm verify

down:      ## 停止并清理
	docker compose down

test-backend:
	cd backend && python -m pytest

test-frontend:
	cd frontend && npm test

e2e:       ## 容器化 Playwright 联调
	docker compose --profile e2e run --rm e2e
