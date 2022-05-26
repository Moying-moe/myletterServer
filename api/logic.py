from __future__ import annotations
from typing import *

import base64
from copy import deepcopy
from datetime import datetime
from io import BytesIO
import json
import math
import random
from hashlib import md5, sha256
import re
from PIL import Image, ImageDraw, ImageFont

from django.http import HttpResponse
from django.utils.decorators import classonlymethod
from django.views.decorators.csrf import csrf_exempt
from django.core import cache

from api.data import LocationName
from api.models import *


PASSWORD_SALT = 'VL~*rNwOTkjlw+/D9EJ3FOnERsvO80'
RSESSION_CACHE_EXP = 1800 # refresh会话缓存的有效时间 0.5小时
VERIFY_CODE_EXP = 180 # 验证码的有效期


class GlobalVars:
    INSTANCE = None
    @staticmethod
    def getInstance() -> GlobalVars:
        if GlobalVars.INSTANCE is None:
            GlobalVars.INSTANCE = GlobalVars()
        return GlobalVars.INSTANCE
    
    ##############################################
    
    availableLocations:List[Tuple[int,int]] = []
    def __init__(self):
        # init availableLocations
        # TODO: 应该做个持久化，不然每次重启服务器都要跑一边user表。有空再弄
        usedLocations = []
        users = User.objects.all()
        for user in users:
            usedLocations.append((user.vlocation.position_x, user.vlocation.position_y))
        for x in range(1920):
            for y in range(1920):
                if (x,y) not in usedLocations:
                    self.availableLocations.append((x,y))


class ErrorNotAllow(BaseException):
    def __init__(self, errCode):
        self.msg = "Interface logic raise ERROR-%d, which is not in the `allow_errors` list" % (errCode)

    def __str__(self):
        return self.msg

    def __repr__(self):
        return self.msg


class Tools:
    @staticmethod
    def getSHA256(string, encoding:str="utf-8") -> str:
        bstring = string.encode(encoding)
        s = sha256(bstring)
        return s.hexdigest()

    @staticmethod
    def getMD5(string, encoding:str="utf-8") -> str:
        bstring = string.encode(encoding)
        m = md5(bstring)
        return m.hexdigest()

    @staticmethod
    def renderJson(obj:Any) -> HttpResponse:
        jsons = json.dumps(obj, ensure_ascii=False)
        return HttpResponse(jsons)

    @staticmethod
    def jsonSuccess(data:Dict) -> HttpResponse:
        return Tools.renderJson({"code": 0, "data": data})

    @staticmethod
    def jsonError(errcode, desc:str) -> HttpResponse:
        return Tools.renderJson({"code": errcode, "reason": desc})

    @staticmethod
    def getRandomString(length:int) -> str:
        useChar = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789~@#_^*%/.+:;"
        res = ""
        for i in range(length):
            res += random.choice(useChar)
        return res
    
    @staticmethod
    def getRandom16bit(length:int) -> str:
        num = random.randint(0, 0x10**(length-1))
        return hex(num)[2:].zfill(length)

    @staticmethod
    def getPasswordHash(password:str) -> str:
        return Tools.getSHA256(password + PASSWORD_SALT)
    
    @staticmethod
    def getNow(_type:str='timestamp') -> Any:
        if _type == 'timestamp':
            return datetime.now().timestamp()
        elif _type == 'datetime':
            return datetime.now()
        else:
            return None
        
    @staticmethod
    def getReFunc(pattern:str, flags=0, full_match:bool = True) -> Callable:
        if full_match:
            if pattern[0] != '^':
                pattern = '^' + pattern
            if pattern[-1] != '$':
                pattern += '$'
                
        prog = re.compile(pattern=pattern, flags=flags)
        def reprogfunc(string:str, *args, **kwargs) -> bool:
            res = prog.match(string, *args, **kwargs)
            return res is not None
        return reprogfunc


class JsonResponse:
    ERR_ARG = 100
    ERR_ARGTYPE = 101
    ERR_METHOD = 102
    ERR_LOGIN_FAIL = 200
    ERR_VERIFY_CODE_FAIL = 201
    ERR_INPUT_USERNAME = 300
    ERR_INPUT_USERNAME_UNIQUE = 301
    ERR_INPUT_PASSWORD = 302
    ERR_INPUT_NICKNAME = 303
    ERR_LIST = {
        # 请求类错误
        ERR_ARG: "请求参数获取失败 或请求方法错误",
        ERR_ARGTYPE: "请求参数类型不正确",
        ERR_METHOD: "请求方式不支持",
        # 身份验证错误
        ERR_LOGIN_FAIL: "登录失败 用户名或密码错误",
        ERR_VERIFY_CODE_FAIL: "验证码错误 或验证码已过期",
        # 输入约束类错误
        ERR_INPUT_USERNAME: "用户名不符合规范",
        ERR_INPUT_USERNAME_UNIQUE: "用户名已被使用",
        ERR_INPUT_PASSWORD: "密码不符合规范",
        ERR_INPUT_NICKNAME: "昵称不符合规范",
        #  查询类错误

    }

    @staticmethod
    def create(code, data=None):
        if code == 0:
            return Tools.renderJson({"code": 0, "data": data})
        else:
            if code in JsonResponse.ERR_LIST:
                return Tools.renderJson({"code": code, "reason": JsonResponse.ERR_LIST[code]})
            else:
                return Tools.renderJson({"code": code, "reason": "Unknown Error"})


class APIInterface:
    # 接口允许的请求类型
    methods:List[str] = ["POST", "GET"]
    # 接口的参数以及参数约束
    args:Dict[str,Tuple] = {}
    # 接口允许返回的错误 ERR_METHOD, ERR_ARG, ERR_ARGTYPE总是被允许的
    allow_errors: List[int] = []
    
    __allow_errors_set: Set[int] = set()

    # 返回值 无需继承
    result:Optional[Dict] = None
    # 错误值 无需继承
    error:Optional[int] = None

    # 接口逻辑 需继承 参数为args中参数（同名） 返回值为True表示成功 返回result False表示失败 返回error
    def logic(self):
        return True

    @classonlymethod
    def get_view(cls) -> Callable:
        cls.allow_errors.extend((JsonResponse.ERR_METHOD, JsonResponse.ERR_ARG, JsonResponse.ERR_ARGTYPE))
        cls.__allow_errors_set = set(cls.allow_errors)

        @csrf_exempt
        def view(request):
            # 验证请求方式
            if request.method not in cls.methods:
                return JsonResponse.create(JsonResponse.ERR_METHOD)  # ERR_METHOD必然在允许范围内

            # 验证请求参数
            if request.method == "POST":
                argDict = request.POST
            else:
                argDict = request.GET
            reqav = RequestArgsVerify(argDict, cls.args)
            retv = reqav.verify()
            if retv != 0:
                # 请求参数有问题 返回错误信息
                if retv not in cls.__allow_errors_set:
                    # 该错误不在allow_errors中
                    raise ErrorNotAllow(retv)
                return JsonResponse.create(retv)

            # 调用接口逻辑
            parg = reqav.getData()
            logicSucc = cls.logic(cls, **parg)

            assert isinstance(logicSucc, bool) # 返回值必须是True或False
            
            if logicSucc:
                # 接口成功调用 返回result
                return JsonResponse.create(0, cls.result)
            else:
                # 接口调用失败 抛出error
                if cls.error not in cls.__allow_errors_set:
                    # 该错误不在allow_errors中
                    raise ErrorNotAllow(cls.error)
                return JsonResponse.create(cls.error)

        return view


class RequestArgsVerify:
    def __init__(self, postObj, args):
        """
        从postObj中提取需要的参数，并对其进行合法性验证
        args的数据结构:
        dict
        {
            'argname': (type, bound1, bound2, err),  type为arg的类型 bound为约束
                                                若为None 则表示类型为str 无约束
        }
        type为int,float等数字型时 bound为上下限 [bound1, bound2]
        type为str时 bound为字符串长度上下限
        type为None时 bound1为一个函数 函数的返回值为真则表示通过
        bound1为None时 表示只进行类型验证 不做数据验证
        err表示数据不符合约束时 返回的错误码
        后面整个部分均为None时 表示本数据既不做验证 也不存储数值
        """
        self.data = {}
        self.args = args
        self.postObj = postObj

    def loadData(self) -> None:
        for k in self.args:
            self.data[k] = self.postObj[k]

    def verify(self) -> int:
        try:
            self.loadData()
        except KeyError:
            return JsonResponse.ERR_ARG

        for k in self.args:
            if self.args[k] is None:
                continue

            # 类型转换
            if self.args[k][0] is not None:
                try:
                    self.data[k] = self.args[k][0](self.data[k])
                except:
                    return JsonResponse.ERR_ARGTYPE

            if self.args[k][1] is None:
                # 只做类型验证 不做数值验证
                continue

            if self.args[k][0] is None:
                # 用户自定义检查函数
                if not self.args[k][1](self.data[k]):
                    return self.args[k][2]
            elif self.args[k][0] == str:
                # 字符串 检查长度
                if not (self.args[k][1] <= len(self.data[k]) <= self.args[k][2]):
                    return self.args[k][3]
            elif self.args[k][0] in (int, float):
                # 数字型 检查数值范围
                if not (self.args[k][1] <= self.data[k] <= self.args[k][2]):
                    return self.args[k][3]
        return 0

    def getData(self) -> Dict:
        return deepcopy(self.data)


class VerifyCode:
    # tools
    RANDOM_CHARS = r'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01234567890123456789'
    def hsv2rgb(self, h, s, v):
        h = float(h)
        s = float(s)
        v = float(v)
        h60 = h / 60.0
        h60f = math.floor(h60)
        hi = int(h60f) % 6
        f = h60 - h60f
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        r, g, b = 0, 0, 0
        if hi == 0: r, g, b = v, t, p
        elif hi == 1: r, g, b = q, v, p
        elif hi == 2: r, g, b = p, v, t
        elif hi == 3: r, g, b = p, q, v
        elif hi == 4: r, g, b = t, p, v
        elif hi == 5: r, g, b = v, p, q
        r, g, b = int(r * 255), int(g * 255), int(b * 255)
        return r, g, b

    def getRandomBgColor(self):
        r = random.randint(0xdd,0xff)
        g = r + random.randint(-0x8,0x8)
        b = r + random.randint(-0x8,0x8)
        return (r,g,b)

    def getRandomFrontColor(self):
        h = random.randint(0,255)
        s = 1
        v = 0.6
        return self.hsv2rgb(h,s,v)

    def getRandomChar(self):
        return random.choice(self.RANDOM_CHARS)

    # draws
    WIDTH = 120
    HEIGHT = 50
    VERIFY_CODE_SALT = 'Z305qHnA23ByD%*3A7^I3*XaL*jq^Q54'
    
    code:Optional[str] = None
    img:Optional[Image.Image] = None
    def __init__(self, seed:str, randomLineFront:int=3, randomLineBack:int=7, randomDotRatio:float=0.05):
        self.seed = seed
        self.randomLineFront = randomLineFront
        self.randomLineBack = randomLineBack
        self.randomDotRatio = randomDotRatio
    
    def drawRotateText(self, angle:float, xy:Tuple, text:str, fill:Tuple, *args, **kwargs) -> None:
        max_dim = max(self.WIDTH, self.HEIGHT)
        mask_size = (max_dim * 2, max_dim * 2)
        mask = Image.new('L', mask_size, 0)

        # add text to mask
        draw = ImageDraw.Draw(mask)
        draw.text((max_dim, max_dim), text, 255, *args, **kwargs)

        # rotate an an enlarged mask to minimize jaggies
        bigger_mask = mask.resize((max_dim*8, max_dim*8),
                                    resample=Image.BICUBIC)
        rotated_mask = bigger_mask.rotate(angle).resize(
            mask_size, resample=Image.LANCZOS)

        # crop the mask to match image
        mask_xy = (max_dim - xy[0], max_dim - xy[1])
        b_box = mask_xy + (mask_xy[0] + self.WIDTH, mask_xy[1] + self.HEIGHT)
        mask = rotated_mask.crop(b_box)

        # paste the appropriate color, with the text transparency mask
        color_image = Image.new('RGBA', (self.WIDTH, self.HEIGHT), fill)
        self.getImage().paste(color_image, mask)
        
    def drawRandomLine(self, color:Tuple) -> None:
        startpos = (random.uniform(0,self.WIDTH), random.uniform(0, self.HEIGHT))
        ang = random.uniform(0, 2*math.pi)
        length = random.uniform(1, 70)
        width = random.randint(1, 2)
        endpos = (
            startpos[0] + length*math.cos(ang),
            startpos[1] + length*math.sin(ang)
        )
        self.draw.line([startpos,endpos], color, width)
    
    def drawImage(self) -> None:
        if self.code is None:
            self.getCode()
        
        angle = [random.uniform(-15,15) for i in range(4)]
        pos = [(random.uniform(5,30), random.uniform(2,8))]
        pos.append((pos[-1][0]+random.uniform(10,30), random.uniform(2,8)))
        pos.append((pos[-1][0]+random.uniform(10,30), random.uniform(2,8)))
        pos.append((pos[-1][0]+random.uniform(10,30), random.uniform(2,8)))

        self.img = Image.new('RGB', (self.WIDTH,self.HEIGHT), self.getRandomBgColor())
        self.draw = ImageDraw.Draw(self.img)
        # 背景随机线
        for i in range(self.randomLineBack):
            self.drawRandomLine(self.getRandomFrontColor())
        # 字符
        for i in range(4):
            ttfont = ImageFont.truetype('./arial%s.ttf'%('bd' if random.random() < 0.5 else ''), random.randint(25,40))
            self.drawRotateText(angle[i], pos[i], self.getCode()[i], self.getRandomFrontColor(), font=ttfont)
        # 前景随机线
        for i in range(self.randomLineFront):
            self.drawRandomLine(self.getRandomFrontColor())
        # 随机点
        for x in range(self.WIDTH):
            for y in range(self.HEIGHT):
                if random.random() < self.randomDotRatio:
                    self.draw.point((x,y), self.getRandomFrontColor())
    
    def isCodeRight(self, code:str) -> bool:
        try:
            _, seedtimestr = self.seed.split(':')
            seedtime = float(seedtimestr)
        except:
            return False
        
        if Tools.getNow() - seedtime > VERIFY_CODE_EXP:
            return False
        
        rcode = self.getCode().casefold()
        code = code.casefold().replace(' ','')
        if code == rcode:
            return True
        else:
            return False
    
    def getImage(self) -> Image.Image:
        if self.img is None:
            self.drawImage()
        return self.img
    
    def getCode(self) -> str:
        if self.code is None:
            random.seed(self.seed + self.VERIFY_CODE_SALT, 2)
            self.code = ''.join((self.getRandomChar() for i in range(4)))
        return self.code
    
    def getBase64(self) -> str:
        if self.img is None:
            self.drawImage()
        buffer = BytesIO()
        self.getImage().save(buffer, format="JPEG")
        bdata = buffer.getvalue()
        return 'data:image/jpg;base64,' + base64.b64encode(bdata).decode('utf-8')

