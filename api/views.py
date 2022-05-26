from __future__ import annotations
from typing import *

from django.db import IntegrityError
from api.logic import APIInterface, JsonResponse, Tools, VerifyCode
from .models import *

# Create your views here.
class VerifyCodeInterface(APIInterface):
    '''
    获取验证码接口
    
    <- randomkey: 验证码随机key
    <- b64image: 验证码base64
    '''
    methods = ['GET', 'POST']
    args:Dict = {
        # NOTHING
    }
    allow_errors:Any = []
    
    def logic(self):
        key = Tools.getRandom16bit(32)+':'+str(Tools.getNow('timestamp'))
        vc = VerifyCode(key, 3, 7, 0.04)
        self.result = {
            'randomkey': key,
            'b64image': vc.getBase64()
        }
        return True

class VerifyCodeTestInterface(APIInterface):
    '''
    验证码测试接口
    '''
    methods = ['GET', 'POST']
    args:Dict = {
        'randomkey': (str, None),
        'verifycode': (str, None)
    }
    allow_errors:Any = [JsonResponse.ERR_VERIFY_CODE_FAIL]
    
    def logic(self, randomkey, verifycode):
        vc = VerifyCode(randomkey)
        if not vc.isCodeRight(verifycode):
            self.error = JsonResponse.ERR_VERIFY_CODE_FAIL
            return False
        
        self.result = {
            'message': 'success'
        }
        return True

class LoginInterface(APIInterface):
    '''
    登录接口
    -> username: 用户名
    -> password: 密码
    -> randomkey: 验证码随机key
    -> verifycode: 验证码
    
    <- session: refresh session id
    '''
    methods = ['POST']
    args: Dict[str, Tuple] = {
        'username': (str, None),
        'password': (str, None),
        'randomkey': (str, None),
        'verifycode': (str, None)
    }
    allow_errors = [JsonResponse.ERR_LOGIN_FAIL, JsonResponse.ERR_VERIFY_CODE_FAIL]
    
    def logic(self, username, password, randomkey, verifycode):
        # 验证码是否正确？
        vc = VerifyCode(randomkey)
        if not vc.isCodeRight(verifycode):
            self.error = JsonResponse.ERR_VERIFY_CODE_FAIL
            return False
        
        try:
            user:User = User.objects.get(username = username)
        except User.DoesNotExist:
            self.error = JsonResponse.ERR_LOGIN_FAIL
            return False
        
        if user.password_hash != Tools.getPasswordHash(password):
            self.error = JsonResponse.ERR_LOGIN_FAIL
            return False
        
        # 登录成功
        # 开启session
        sessionCode = user.createSession(int(Tools.getNow()))
        self.result = {
            'session': sessionCode
        }
        return True

class RegisterInterface(APIInterface):
    '''
    注册接口
    -> username: 用户名 4-30字符 字母数字和@-_*%+ 不重复
    -> password: 密码 6-25字符 字母数字和@-_*%+
    -> nickname: 昵称 2-30字符
    
    <- message: 'success' 表示注册成功
    '''
    methods: List[str] = ['POST']
    args: Dict[str, Tuple] = {
        'username': (str, Tools.getReFunc(r'[a-zA-Z0-9@\-_\*%]{4,30}')),
        'password': (str, Tools.getReFunc(r'[a-zA-Z0-9@\-_\*%]{6,25}')),
        'nickname': (str, Tools.getReFunc(r'.{2,30}'))
    }
    allow_errors: List[int] = [JsonResponse.ERR_INPUT_USERNAME, JsonResponse.ERR_INPUT_USERNAME_UNIQUE,
                               JsonResponse.ERR_INPUT_PASSWORD, JsonResponse.ERR_INPUT_NICKNAME]
    
    def logic(self, username, password, nickname):
        vpos = VirtualLocation.getRandomPosition()
        vlocation = VirtualLocation.createLocationByPos(vpos)
        vlocation.save()
        
        try:
            user = User(username = username, password_hash = Tools.getPasswordHash(password),
                        nickname = nickname, vlocation = vlocation, session = None)
            user.save()
        except IntegrityError:
            # username重复了 这里不想查表查重 怕有多线程同步的问题
            self.error = JsonResponse.ERR_INPUT_USERNAME_UNIQUE
            return False
        
        self.result = {
            'message': 'success'
        }
        return True