from __future__ import annotations
from typing import Tuple

import random

from django.db import models
from django.core import cache

from api.data import LocationName
from api.logic import RSESSION_CACHE_EXP, GlobalVars, Tools

# Create your models here.

class VirtualLocation(models.Model):
    position_x = models.IntegerField() # 虚拟地址x坐标
    position_y = models.IntegerField() # 虚拟地址y坐标
    city_name = models.CharField(max_length=20) # 虚拟地址 城市名
    block_name = models.CharField(max_length=20) # 虚拟地址 市区名
    community_name = models.CharField(max_length=20) # 虚拟地址 小区名
    building_index = models.SmallIntegerField() # 虚拟地址 幢号
    room_index = models.SmallIntegerField() # 虚拟地址 门牌号
    # 虚拟地址形如：[幸福]城 [弄堂]区 [宣和花园] [30]幢 [207]
    
    def getAddressInfo(self) -> Tuple[str,str,str,str,str]:
        '''获取地址信息元组'''
        posx = self.position_x
        posy = self.position_y
        city_x = posx // 480
        city_y = posy // 480
        city_id = city_y*4 + city_x
        posx %= 640
        posy %= 640
        
        block_x = posx // 160
        block_y = posy // 160
        block_id = block_y*3 + block_x
        posx %= 160
        posy %= 160
        
        community_x = posx // 40
        community_y = posy // 40
        community_id = community_y*4 + community_x
        posx %= 40
        posy %= 40
        
        building_x = posx // 10
        building_y = posy // 10
        building_id = building_y*4 + building_x
        posx %= 10
        posy %= 10
        
        room_ind = posy*4 + posx
        room_id = (room_ind//6+1)*100 + (room_ind%6+1)
        
        return (LocationName.City[city_id], LocationName.Block[city_id][block_id],
                LocationName.Community[city_id][block_id][community_id], str(building_id), str(room_id))

    def getFullAddress(self, sep:str=' ') -> str:
        '''获取完整地址名'''
        lInfo = list(self.getAddressInfo())
        lInfo[0] += '城'
        lInfo[1] += '区'
        lInfo[3] += '幢'
        return sep.join(lInfo)
    
    @staticmethod
    def createLocationByPos(pos:Tuple[int, int]) -> VirtualLocation:
        '''从pos创建location
        注意: 返回的vloc对象尚未写入数据库'''
        posx = pos[0]
        posy = pos[1]
        city_x = posx // 480
        city_y = posy // 480
        city_id = city_y*4 + city_x
        posx %= 640
        posy %= 640
        
        block_x = posx // 160
        block_y = posy // 160
        block_id = block_y*3 + block_x
        posx %= 160
        posy %= 160
        
        community_x = posx // 40
        community_y = posy // 40
        community_id = community_y*4 + community_x
        posx %= 40
        posy %= 40
        
        building_x = posx // 10
        building_y = posy // 10
        building_id = building_y*4 + building_x
        posx %= 10
        posy %= 10
        
        room_ind = posy*4 + posx
        room_id = (room_ind//6+1)*100 + (room_ind%6+1)
        
        vloc = VirtualLocation(position_x = pos[0], position_y = pos[1], city_name = LocationName.City[city_id],
                               block_name = LocationName.Block[city_id][block_id], 
                               community_name = LocationName.Community[city_id][block_id][community_id],
                               building_index = str(building_id), room_index = str(room_id))
        return vloc
    
    @staticmethod
    def getRandomPosition():
        '''获取一个随机的可用坐标'''
        randi = random.randint(0, len(GlobalVars.getInstance().availableLocations)-1)
        return GlobalVars.getInstance().availableLocations.pop(randi)

class User(models.Model):
    username = models.CharField(max_length=30, unique=True) # 用户名 唯一
    password_hash = models.CharField(max_length=64) # 密码的哈希值（64位16进制小写字符串）
    nickname = models.CharField(max_length=30, null=True) # 昵称
    reg_date = models.DateTimeField(auto_now_add=True) # 注册时间
    exp = models.BigIntegerField(default=0) # 经验值
    vlocation = models.ForeignKey(VirtualLocation, null=True, on_delete=models.SET_NULL) # 虚拟地址
    session = models.CharField(max_length=64, null=True) # refresh会话码
    
    def createSession(self, createTime:int) -> str:
        username = self.username
        sessionCode = Tools.getSHA256('%s%d%s'%(username, createTime, Tools.getRandomString(32))) + \
                        ':%d'%(createTime)

        rsessionCache = cache.caches['rsession']
        rsessionCache.set(username, sessionCode, RSESSION_CACHE_EXP)
        
        self.session = sessionCode
        self.save()
        
        return sessionCode
    
    @staticmethod
    def verifySession(username, sessionCode:str) -> bool:
        rsessionCache = cache.caches['rsession']
        rightSessionCode = rsessionCache.get(username, '!NOCACHE!')
        if rightSessionCode != '!NOCACHE!':
            # 找到cache 直接比较
            return sessionCode == rightSessionCode
        
        # 未找到 查表
        user = User.objects.get(username=username)
        rightSessionCode = user.session
        return sessionCode == rightSessionCode and rightSessionCode is not None