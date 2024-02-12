# -*- coding: windows-1251 -*-
import asyncio
import uuid
import websockets
from websockets.exceptions import WebSocketException
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, MediaStreamTrack, RTCIceCandidate
from msgpack import packb, unpackb
from PyQt6.QtCore import pyqtSignal, QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsPixmapItem, QGraphicsView
import qasync
from fullSCR import Ui_fullSCR
import sys

KEY_MAP = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Control: "control",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_CapsLock: "caps_lock",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win",
    Qt.Key.Key_Escape: "escape",
    Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2", Qt.Key.Key_F3: "f3", Qt.Key.Key_F4: "f4",
    Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6", Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8",
    Qt.Key.Key_F9: "f9", Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
    Qt.Key.Key_Print: "print_screen", Qt.Key.Key_ScrollLock: "scroll_lock",
    Qt.Key.Key_Insert: "insert", Qt.Key.Key_Delete: "delete", Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "page_up", Qt.Key.Key_PageDown: "page_down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Up: "up", Qt.Key.Key_Right: "right", Qt.Key.Key_Down: "down",
    # NumPad
    Qt.Key.Key_0: "NumPad0", Qt.Key.Key_1: "NumPad1", Qt.Key.Key_2: "NumPad2",
    Qt.Key.Key_3: "NumPad3", Qt.Key.Key_4: "NumPad4", Qt.Key.Key_5: "NumPad5",
    Qt.Key.Key_6: "NumPad6", Qt.Key.Key_7: "NumPad7", Qt.Key.Key_8: "NumPad8",
    Qt.Key.Key_9: "NumPad9", Qt.Key.Key_Period: "NumPadDecimal",
    Qt.Key.Key_Plus: "NumPadAdd", Qt.Key.Key_Minus: "NumPadSubtract",
    Qt.Key.Key_Asterisk: "NumPadMultiply", Qt.Key.Key_Slash: "NumPadDivide",
    # Дополнительно
    Qt.Key.Key_Enter: "NumPadEnter", Qt.Key.Key_Equal: "NumPadEqual"
}

class AsyncEvent(QEvent):
    def __init__(self, fn, *args, **kwargs):
        super().__init__(QEvent.Type(QEvent.registerEventType()))
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

class Admin(QMainWindow, Ui_fullSCR):
    image_signal = pyqtSignal(QImage)

    def __init__(self, host, port, parent=None):
        super(Admin, self).__init__(parent)
        self.setupUi(self)

        self.loop = asyncio.new_event_loop()
        self.host = host
        self.url = f"ws://{host}:{port}/ws"
        self.client_id = uuid.getnode()
        self.pc = None
        self.websocket = None

        self.graphicsView = GraphicsView(self)
        self.setCentralWidget(self.graphicsView)

        self.image_signal.connect(self.update_image)

    def update_image(self, image: QImage):
        pixmap = QPixmap.fromImage(image)
        scene = QGraphicsScene(self)
        scene.addItem(QGraphicsPixmapItem(pixmap))
        self.graphicsView.setScene(scene)
        self.graphicsView.fitInView(scene.itemsBoundingRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def event(self, event):
        if isinstance(event, AsyncEvent):
            asyncio.ensure_future(event.fn(*event.args, **event.kwargs))
            return True
        return super().event(event)

    def send_cursor_position_async(self, x, y):
        QCoreApplication.postEvent(self, AsyncEvent(self.send_cursor_position, x, y))

    async def send_cursor_position(self, x, y):
        if self.websocket:
            data = packb({"x": x, "y": y})
            await self.websocket.send(data)
            
    async def send_mouse_event(self, event_type, button, x, y):
        data = packb({"event": "mouse", "type": event_type, "button": button, "x": x, "y": y})
        await self.send(data)

    async def send_wheel_event(self, delta):
        data = packb({"event": "wheel", "delta": delta})
        await self.send(data)

    def send_mouse_event_async(self, event_type, button, x, y):
        QCoreApplication.postEvent(self, AsyncEvent(self.send_mouse_event, event_type, button, x, y))

    def send_wheel_event_async(self, delta):
        QCoreApplication.postEvent(self, AsyncEvent(self.send_wheel_event, delta))
        
    def send_keyboard_event_async(self, event_type, key_text):
        QCoreApplication.postEvent(self, AsyncEvent(self.send_keyboard_event, event_type, key_text))

    async def send_keyboard_event(self, event_type, key_text):
        data = packb({"event": "keyboard", "type": event_type, "key": key_text})
        await self.send(data)

    async def connect(self):
        while not self.websocket:
            try:
                self.websocket = await websockets.connect(self.url)
                await self.auth()
                await self.handle_messages()
            except (ConnectionRefusedError, asyncio.TimeoutError, WebSocketException) as e:
                print(f"Connection error: {e}, retrying in 5 seconds...")
                await asyncio.sleep(5)

    async def auth(self):
        await self.send({"command": "auth", "client_id": self.client_id})

    async def setup_peer_connection(self, data):
        self.pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[
                    RTCIceServer(
                        urls=f"turn:{self.host}",
                        username=data.get("username"),
                        credential=data.get("password")
                    )
                ]
            )
        )
        self.pc.on("icecandidate", self.on_icecandidate)
        self.pc.on("iceconnectionstatechange", self.on_iceconnectionstatechange)
        self.pc.on("track", self.on_track)

    async def on_icecandidate(self, event):
        if event.candidate:
            await self.send({
                "command": "candidate",
                "client_id": self.client_id,
                "candidate": {
                    "candidate": event.candidate.candidate,
                    "sdpMid": event.candidate.sdpMid,
                    "sdpMLineIndex": event.candidate.sdpMLineIndex,
                }
            })

    async def on_iceconnectionstatechange(self):
        print(f"ICE Connection State has changed to {self.pc.iceConnectionState}")

    async def on_track(self, track):
        while True:
            frame = await track.recv()
            img = frame.to_ndarray(format="rgb24")
            h, w, ch = img.shape
            bytesPerLine = ch * w
            image = QImage(img.data, w, h, bytesPerLine, QImage.Format_RGB888)
            self.image_signal.emit(image.copy())

    async def handle_messages(self):
        while self.websocket:
            message = await self.websocket.recv()
            data = unpackb(message)
            command = data.get("command")
            if command == "offer":
                await self.handle_offer(data)
            elif command == "candidate":
                await self.handle_candidate(data)

    async def handle_offer(self, offer_data):
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        await self.send({
            "command": "answer",
            "sdp": self.pc.localDescription.sdp,
            "type": self.pc.localDescription.type,
            "target_id": offer_data.get("client_id")
        })

    async def handle_candidate(self, candidate_data):
        candidate = RTCIceCandidate(**candidate_data)
        await self.pc.addIceCandidate(candidate)

    async def send(self, data):
        await self.websocket.send(packb(data))

    def start_app(self):
        import sys

        self.show()
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)

        with loop:
            loop.run_until_complete(self.connect())

class GraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super(GraphicsView, self).__init__(parent)
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        super(GraphicsView, self).mouseMoveEvent(event)
        pos = event.position()
        print(f"Mouse Move: x={pos.x()}, y={pos.y()}")
        if self.parent():
            self.parent().send_cursor_position_async(pos.x(), pos.y())
            
    def mousePressEvent(self, event):
        super(GraphicsView, self).mousePressEvent(event)
        button = event.button()
        pos = event.position()
        print(f"Mouse Press: button={button}, x={pos.x()}, y={pos.y()}")
        self.parent().send_mouse_event_async("press", button, pos.x(), pos.y())

    def mouseReleaseEvent(self, event):
        super(GraphicsView, self).mouseReleaseEvent(event)
        button = event.button()
        pos = event.position()
        print(f"Mouse Release: button={button}, x={pos.x()}, y={pos.y()}")
        self.parent().send_mouse_event_async("release", button, pos.x(), pos.y())
        
    def wheelEvent(self, event):
        super(GraphicsView, self).wheelEvent(event)
        delta = event.angleDelta().y()
        print(f"Mouse Wheel: delta={delta}")
        self.parent().send_wheel_event_async(delta)
        
    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        key_text = event.text() if event.text() else KEY_MAP.get(event.key(), None)
        if key_text:
            print(f"Key Press: {key_text}")
            self.parent().send_keyboard_event_async("press", key_text)

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        key_text = event.text() if event.text() else KEY_MAP.get(event.key(), None)
        if key_text:
            print(f"Key Release: {key_text}")
            self.parent().send_keyboard_event_async("release", key_text)

if __name__ == "__main__":
    app = qasync.QApplication(sys.argv)
    admin = Admin('127.0.0.1', 8080)
    admin.start_app()
