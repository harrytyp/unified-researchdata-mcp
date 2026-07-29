import sys
import logging
import requests as req_lib

logger = logging.getLogger('instrument-data-loader')

def init_metainfo():
    from nomad.datamodel import User
    
    @staticmethod
    def patched_user_get(*args, **kwargs):
        user_id = kwargs.get('user_id') or (args[0] if args else None)
        if not user_id:
            return None
        
        try:
            resp = req_lib.get(
                f'https://nomad-lab.eu/prod/v1/api/v1/users?user_id={user_id}',
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data'):
                    u = data['data'][0]
                    return User(
                        user_id=u['user_id'],
                        username=u.get('username'),
                        first_name=u.get('first_name'),
                        last_name=u.get('last_name'),
                        email=u.get('email'),
                        affiliation=u.get('affiliation'),
                    )
        except Exception as e:
            logger.warning('Central API failed: %s', e)
        
        try:
            return User(
                user_id=user_id,
                username=user_id[:8],
                first_name='',
                last_name='',
                email='',
            )
        except Exception as e:
            logger.error('Failed to create minimal user: %s', e)
        
        return None
    
    User.get = patched_user_get
    logger.info('User.get patched')

init_metainfo()
