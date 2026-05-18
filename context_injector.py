"""Real-time context injector: local time + weather for persona prompts."""

import time
from datetime import datetime

import httpx

# Cache weather for 10 minutes to avoid hitting rate limits
_cache: dict = {}


def _meal_hint(hour: int) -> str:
    """返回注入 system 消息的时段标签。"""
    if 6 <= hour < 9:
        return "早晨"
    elif 9 <= hour < 11:
        return "上午"
    elif 11 <= hour < 13:
        return "中午"
    elif 13 <= hour < 17:
        return "下午"
    elif 17 <= hour < 20:
        return "傍晚"
    elif 20 <= hour < 23:
        return "晚间"
    else:
        return "深夜"


def meal_prefix(hour: int) -> str:
    """防幻觉核心：直接命令 AI 的回复开头，DeepSeek 无法跳过。

    格式：[时间戳|你必须说X|关心Y|禁止提Z]
    极短、结构化、硬约束。不描述——直接命令。
    """
    if 6 <= hour < 9:
        return f"[现在{hour}点|你必须说早上好|只关心早饭吃了没|禁止提午饭晚饭睡觉]"
    elif 9 <= hour < 11:
        return f"[现在{hour}点|你必须说上午好|关心加餐/水果|禁止提早饭-已过|禁止提午饭-还早]"
    elif 11 <= hour < 13:
        return f"[现在{hour}点|你必须说中午好|只关心午饭吃了没|禁止提早饭晚饭]"
    elif 13 <= hour < 17:
        return f"[现在{hour}点|你必须说下午好|关心下午茶/水果|禁止提早饭午饭晚饭-都吃过了]"
    elif 17 <= hour < 20:
        return f"[现在{hour}点|你必须说晚上好|只关心晚饭吃了没|禁止提早饭午饭]"
    elif 20 <= hour < 23:
        return f"[现在{hour}点|你必须说晚上好|提醒别吃夜宵早点睡|禁止提早饭午饭晚饭]"
    else:
        return f"[现在{hour}点|你必须说这么晚了|只催睡觉|禁止提任何吃饭-几点了还吃]"


async def build_context(location: str = "北京") -> str:
    """返回一段注入到对话中的实时上下文文本（异步）。"""
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]

    time_info = (
        f"现在是{now.year}年{now.month}月{now.day}日 {weekday} "
        f"北京时间{now.hour:02d}:{now.minute:02d}。"
    )

    weather_info = await _get_weather(location)
    meal_hint = _meal_hint(now.hour)

    return (
        f"[系统实时信息]\n{time_info}\n{weather_info}\n{meal_hint}\n"
        f"请在对话中自然地运用以上时间和天气信息。"
    )


async def _get_weather(location: str) -> str:
    now = time.time()
    if location in _cache and now - _cache[location]["ts"] < 600:
        return _cache[location]["text"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://wttr.in/{location}",
                params={"format": "j1"},
                timeout=10,
            )
            resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        weather_desc = current["weatherDesc"][0]["value"]
        temp_c = current["temp_C"]
        feels_like = current["FeelsLikeC"]
        humidity = current["humidity"]
        wind_speed = current["windspeedKmph"]

        text = (
            f"{location}当前天气：{weather_desc}，气温{temp_c}°C（体感{feels_like}°C），"
            f"湿度{humidity}%，风速{wind_speed}km/h。"
        )

        forecast = data.get("weather", [])
        if forecast:
            today = forecast[0]
            text += (
                f"今天气温范围{today['mintempC']}°C ~ {today['maxtempC']}°C。"
            )
            if len(forecast) > 1:
                tomorrow = forecast[1]
                text += (
                    f"明天：{tomorrow['weatherDesc'][0]['value']}，"
                    f"气温{tomorrow['mintempC']}°C ~ {tomorrow['maxtempC']}°C。"
                )

        _cache[location] = {"ts": now, "text": text}
        return text

    except Exception as e:
        print(f"[context_injector] 天气获取失败 ({location}): {e}")
        fallback = f"{location}天气：暂时无法获取天气数据，请提醒用户自行查看天气预报。"
        _cache[location] = {"ts": now, "text": fallback}
        return fallback
