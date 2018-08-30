# coding: utf-8
"""
Отправка показаний счетчика воды на pgu.mos.ru
Метод: send
Показания в виде: {"counters":{"счетчик1":"значение","счетчик2":"значение"}}
Параметры конфигурирования:
pgu_water:
  username: ""
  password: ""
  paycode: ""
  flat: ""

"""
import logging
import requests
import re
from datetime import timedelta, datetime

import voluptuous as vol

from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.helpers.restore_state import async_get_last_state
from homeassistant.helpers import event
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

ATTR_COUNTERS = 'counters'



DOMAIN = 'pgu_water'

ATTR_INFO_NAME = 'Last info'
ATTR_INFO = 'pgu_water.last_info'

ATTR_CODE = 'pgu_water.last_code'


CONF_USERNAME = 'username'
CONF_PASSWORD = 'password'
CONF_PAYCODE = 'paycode'
CONF_FLAT = 'flat'


CONFIG_SCHEMA = vol.Schema({DOMAIN: {
    vol.Optional(CONF_USERNAME, default=None): cv.string,
    vol.Optional(CONF_PASSWORD, default=None): cv.string,
    vol.Optional(CONF_PAYCODE, default=None): cv.string,
    vol.Optional(CONF_FLAT, default=None): cv.string,
}}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass, config):
    """Инициализация"""
    conf = config.get(DOMAIN, {})

    last_state = await async_get_last_state(hass, ATTR_INFO)
    _LOGGER.debug("Last info: %s", last_state)
    
    hass.states.async_set(ATTR_INFO, last_state.state if last_state else None,
                              {ATTR_FRIENDLY_NAME: ATTR_INFO_NAME})

    last_state = await async_get_last_state(hass, ATTR_CODE)
    _LOGGER.debug("Last code: %s", last_state)
    
    hass.states.async_set(ATTR_CODE, last_state.state if last_state else None)
    
    _LOGGER.debug("CONF username: %s", conf[CONF_USERNAME])
    _LOGGER.debug("CONF password: %s", conf[CONF_PASSWORD])
    _LOGGER.debug("CONF paycode: %s",  conf[CONF_PAYCODE])
    _LOGGER.debug("CONF flat: %s",     conf[CONF_FLAT])

    def handle_send(call):
        counters = call.data.get(ATTR_COUNTERS)
        _LOGGER.debug("Counters: %s", counters)  

        date=datetime.today().date()
        last_day_of_month= (date.replace(day=31) if date.month == 12 else date.replace(month=date.month+1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
        _LOGGER.debug("last_day_of_month: %s", last_day_of_month) 

        """ Create HTTP session """
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'})

        """ AUTH """
        response = s.get('https://my.mos.ru/my/')
        response = s.post('https://oauth20.mos.ru/sps/j_security_check',
                data={'j_username': conf[CONF_USERNAME],'j_password': conf[CONF_PASSWORD],'accessType':'phone'},
                headers={'referer': 'https://my.mos.ru/my/'})

        response = s.get('https://my.mos.ru/my/')
        if re.search(r'oauth20.mos.ru', response.text) is not None:
            _LOGGER.error("AUTH Error")
            hass.states.async_set(ATTR_CODE, 1)      
            hass.states.async_set(ATTR_INFO, "Ошибка авторизации")
            return

        """ Get Counters """
        response = s.get('https://www.mos.ru/pgu/ru/application/guis/1111/',headers={'referer': 'https://my.mos.ru/my/'})
        response = s.post('https://www.mos.ru/pgu/common/ajax/index.php',
            data={'ajaxAction':'getCountersInfo',
                'ajaxModule':'Guis',
                'items[flat]': conf[CONF_FLAT],
                'items[paycode]': conf[CONF_PAYCODE]
                },headers={'referer': 'https://www.mos.ru/pgu/ru/application/guis/1111/'})
        info=response.json()

        if 'error' in info.keys():
            _LOGGER.error("CountersInfo Error %s",info['error'])
            hass.states.async_set(ATTR_CODE, 1)      
            hass.states.async_set(ATTR_INFO, info['error'])
            return
   
        countersList={ i['counterId']: i for i in info['counter'] }    
        _LOGGER.debug("CountersList: %s", countersList)  

        for i in counters:
            if  i not in countersList:
                _LOGGER.error(" %s not in CountersInfo",i)
                hass.states.async_set(ATTR_CODE, 1)      
                hass.states.async_set(ATTR_INFO, "Счетчика %s нет в списке" % (i))
                return

            """ SEND NEW INFO """
            cdata={'ajaxAction':'addCounterInfo',
                    'ajaxModule':'Guis',
                    'items[flat]':conf[CONF_FLAT],
                    'items[paycode]': conf[CONF_PAYCODE],
                    'items[indications][0][counterNum]': i,
                    'items[indications][0][counterVal]': counters[i],
                    'items[indications][0][num]': countersList[i]['num'],
                    'items[indications][0][period]': last_day_of_month 
                    }
            _LOGGER.debug("Counter Add data: %s", cdata)
            response = s.post('https://www.mos.ru/pgu/common/ajax/index.php',
                data=cdata,headers={'referer': 'https://www.mos.ru/pgu/ru/application/guis/1111/'})
            _LOGGER.debug("Counter Add response: %s", response.text)
            info=response.json()
            if info['code']:
                _LOGGER.error("Counter Add error %s",info)
                hass.states.async_set(ATTR_CODE, info['code'])      
                hass.states.async_set(ATTR_INFO, "%s за %s: %s" % (i,last_day_of_month,info['error']))
                return    
            
        hass.states.async_set(ATTR_CODE, 0)        
        hass.states.async_set(ATTR_INFO, "Переданы показания за %s" % (last_day_of_month))
        return

    hass.services.async_register(DOMAIN, 'send', handle_send)
    return True 
