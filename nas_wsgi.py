"""NAS and final-cutover entry point; maintenance is disabled by default."""
from app import app
from deploy.nas.maintenance import MaintenanceGate
application = MaintenanceGate(app.wsgi_app)
