import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from netboot.hostutils import Host


class CabinetException(Exception):
    pass


class Cabinet:
    STATE_STARTUP = "startup"
    STATE_WAIT_FOR_CABINET_POWER_ON = "wait_power_on"
    STATE_SEND_CURRENT_GAME = "send_game"
    STATE_WAIT_FOR_CABINET_POWER_OFF = "wait_power_off"

    def __init__(self, ip: str, description: str, filename: str, target: Optional[str] = None, version: Optional[str] = None) -> None:
        self.description: str = description
        self.__host: Host = Host(ip, target=target, version=version)
        self.__lock: threading.Lock = threading.Lock()
        self.__current_filename: str = filename
        self.__new_filename: str = filename
        self.__state: Tuple[str, int] = (self.STATE_STARTUP, 0)

    @property
    def ip(self) -> str:
        return self.__host.ip

    @property
    def target(self) -> str:
        return self.__host.target

    @property
    def version(self) -> str:
        return self.__host.version

    @property
    def filename(self) -> str:
        with self.__lock:
            return self.__new_filename

    @filename.setter
    def filename(self, new_filename: str) -> None:
        with self.__lock:
            self.__new_filename = new_filename

    def tick(self) -> None:
        """
        Tick the state machine forward.
        """

        with self.__lock:
            self.__host.tick()
            current_state = self.__state[0]

            # Startup state, only one transition to waiting for cabinet
            if current_state == self.STATE_STARTUP:
                self.__state = (self.STATE_WAIT_FOR_CABINET_POWER_ON, 0)
                return

            # Wait for cabinet to power on state, transition to sending game
            # if the cabinet is active, transition to self if cabinet is not.
            if current_state == self.STATE_WAIT_FOR_CABINET_POWER_ON:
                if self.__host.alive:
                    self.__host.send(self.__new_filename)
                    self.__state = (self.STATE_SEND_CURRENT_GAME, 0)
                return

            # Wait for send to complete state. Transition to waiting for
            # cabinet power on if transfer failed. Stay in state if transfer
            # continuing. Transition to waint for power off if transfer success.
            if current_state == self.STATE_SEND_CURRENT_GAME:
                if self.__host.status == Host.STATUS_INACTIVE:
                    raise Exception("State error, shouldn't be possible!")
                elif self.__host.status == Host.STATUS_TRANSFERRING:
                    current, total = self.__host.progress
                    self.__state = (self.STATE_SEND_CURRENT_GAME, int(float(current * 100) / float(total)))
                elif self.__host.status == Host.STATUS_FAILED:
                    self.__state = (self.STATE_WAIT_FOR_CABINET_POWER_ON, 0)
                elif self.__host.status == Host.STATUS_COMPLETED:
                    self.__host.reboot()
                    self.__state = (self.STATE_WAIT_FOR_CABINET_POWER_OFF, 0)
                return

            # Wait for cabinet to turn off again. Transition to waiting for
            # power to come on if the cabinet is inactive. Transition to
            # waiting for power to come on if game changes. Stay in state
            # if cabinet stays on.
            if current_state == self.STATE_WAIT_FOR_CABINET_POWER_OFF:
                if not self.__host.alive:
                    self.__state = (self.STATE_WAIT_FOR_CABINET_POWER_ON, 0)
                elif self.__current_filename != self.__new_filename:
                    self.__current_filename = self.__new_filename
                    self.__state = (self.STATE_WAIT_FOR_CABINET_POWER_ON, 0)
                return

            raise Exception("State error, impossible state!")

    @property
    def state(self) -> Tuple[str, int]:
        """
        Returns the current state as a string, and the progress through that state
        as an integer, bounded between 0-100.
        """
        with self.__lock:
            return self.__state


class CabinetManager:
    def __init__(self, cabinets: Sequence[Cabinet]) -> None:
        self.__cabinets: Dict[str, Cabinet] = {cab.ip: cab for cab in cabinets}
        self.__lock: threading.Lock = threading.Lock()
        self.__thread: threading.Thread = threading.Thread(target=self.__poll_thread)
        self.__thread.setDaemon(True)
        self.__thread.start()

    def __poll_thread(self) -> None:
        while True:
            with self.__lock:
                cabinets: List[Cabinet] = [cab for _, cab in self.__cabinets.items()]

            for cabinet in cabinets:
                cabinet.tick()

            time.sleep(1)

    @property
    def cabinets(self) -> List[Cabinet]:
        with self.__lock:
            return [cab for _, cab in self.__cabinets.items()]

    def cabinet(self, ip: str) -> Cabinet:
        with self.__lock:
            if ip not in self.__cabinets:
                raise CabinetException(f"There is no cabinet with the IP {ip}")
            return self.__cabinets[ip]

    def add_cabinet(self, cab: Cabinet) -> None:
        with self.__lock:
            if cab.ip in self.__cabinets:
                raise CabinetException(f"There is already a cabinet with the IP {cab.ip}")
            self.__cabinets[cab.ip] = cab

    def remove_cabinet(self, ip: str) -> None:
        with self.__lock:
            if ip not in self.__cabinets:
                raise CabinetException(f"There is no cabinet with the IP {ip}")
            del self.__cabinets[ip]

    def cabinet_exists(self, ip: str) -> bool:
        with self.__lock:
            return ip in self.__cabinets
