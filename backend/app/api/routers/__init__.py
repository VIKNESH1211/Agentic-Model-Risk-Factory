from app.api.routers import catalog, evidence, factory, knowledge, library, monitoring, system

ROUTERS = [catalog.router, knowledge.router, factory.router, evidence.router, monitoring.router, library.router, system.router]
