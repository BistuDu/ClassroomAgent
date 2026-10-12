import uvicorn
from .config import settings

if __name__=='__main__':
    uvicorn.run('backend.app:app',host='127.0.0.1',port=settings.openmaic_port,access_log=False)
