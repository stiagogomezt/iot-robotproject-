"""
pico_flash/status_task.py
Tarea periódica de latido (Heartbeat) a 1 Hz (1000 ms) y refresco visual en OLED.
Publica telemetría vital en status/heartbeat y mantiene al usuario informado en pantalla.
"""

import gc
import time
from task import Task
import robot_config


class StatusTask(Task):
    """
    Tarea periódica (period_ms=1000, priority=5) encargada del latido del robot,
    recolección de telemetría de red/memoria y actualización del display OLED.
    """

    def __init__(self, scheduler, node, net, mqtt, car, oled=None, door=None, motion_exec=None, period_ms=1000):
        super().__init__(scheduler, period_ms=period_ms, priority=5, name="StatusHeartbeat")
        self.node = node
        self.net = net
        self.mqtt = mqtt
        self.car = car
        self.oled = oled
        self.door = door
        self.motion_exec = motion_exec
        self.boot_time = time.time()
        self.heartbeat_counter = 0
        self.scroll_offset = 0

    def set_scroll_offset(self, offset):
        self.scroll_offset = max(0, min(3, int(offset)))

    def update(self):
        self.heartbeat_counter += 1
        uptime_s = time.time() - self.boot_time

        wifi_ok = self.net.is_connected()
        mqtt_ok = self.mqtt.is_connected if self.mqtt is not None else False
        ntp_ok = self.net.ntp_ok
        iso_utc = self.net.get_iso_utc()
        mem_free = gc.mem_free()
        car_moving = self.car.is_moving if self.car is not None else False
        is_locked = bool(
            (self.motion_exec is not None and getattr(self.motion_exec, "is_locked", False))
            or (self.car is not None and getattr(self.car, "is_locked", False))
        )

        door_val = None
        if self.door is not None:
            try:
                door_val = self.door.value()
            except Exception:
                pass

        # 1. Telemetría a publicar en MQTT
        heartbeat_data = {
            "robot_id": robot_config.ROBOT_ID,
            "node": robot_config.NODE_NAME,
            "uptime_s": uptime_s,
            "heartbeat_seq": self.heartbeat_counter,
            "wifi_ok": wifi_ok,
            "ip": self.net.get_ip(),
            "rssi": self.net.get_rssi(),
            "mqtt_ok": mqtt_ok,
            "ntp_ok": ntp_ok,
            "utc": iso_utc,
            "mem_free_bytes": mem_free,
            "car_moving": car_moving,
            "locked": is_locked,
        }
        if door_val is not None:
            heartbeat_data["door_open"] = bool(door_val == 1)

        # Publicar heartbeat
        if self.node is not None and mqtt_ok:
            self.node.publish("status/heartbeat", heartbeat_data)

        # 2. Actualizar pantalla OLED si está presente
        if self.oled is not None and self.oled.is_present:
            time_part = iso_utc[11:19] if len(iso_utc) >= 19 else "--:--:--"
            mot_str = "MOV" if car_moving else "STOP"
            door_str = "ABIERTO" if door_val == 1 else "CERR" if door_val == 0 else "--"
            wf_str = "OK" if wifi_ok else "NO"
            mq_str = "OK" if mqtt_ok else "OFF"
            ntp_str = "OK" if ntp_ok else "NO"
            mem_kb = mem_free // 1024

            if is_locked:
                estado_str = "BLOQUEADO"
            elif mqtt_ok and wifi_ok:
                estado_str = "ONLINE"
            else:
                estado_str = "STANDBY"

            line1 = f"R{robot_config.ROBOT_ID}: {estado_str}"
            line2 = f"WF:{wf_str} IP:{self.net.get_ip()[:12]}"
            line3 = f"MQ:{mq_str} NTP:{ntp_str} P:{door_str}"
            line4 = f"UTC: {time_part}"
            line5 = f"MOT:{mot_str} #{self.heartbeat_counter}"
            line6 = f"MEM:{mem_kb}KB libre"

            all_lines = [line1, line2, line3, line4, line5, line6]
            visible = all_lines[self.scroll_offset:]
            self.oled.show_status(*visible)

