# -*- coding: utf-8 -*-
'''

관련 포스팅
https://blog.naver.com/zacra/223622479916
위 포스팅을 꼭 참고하세요!!!

'''
import telegram_alert
# import slack_alert
# import discord_alert
# import kakao_alert


def SendMessage(msg):

    telegram_alert.SendMessage(msg)

    # slack_alert.SendMessage(msg)

    # discord_alert.SendMessage(msg)

    # kakao_alert.SendMessage(msg)
