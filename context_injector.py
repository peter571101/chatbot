"""Real-time context injector: local time + weather for persona prompts."""

import time
from datetime import datetime

import httpx

# Cache weather for 10 minutes to avoid hitting rate limits
_cache: dict = {}


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

    return (
        f"[系统实时信息]\n{time_info}\n{weather_info}\n"
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
