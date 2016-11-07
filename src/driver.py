from IxNetwork import IxNet
from cloudshell.api.cloudshell_api import CloudShellAPISession
from cloudshell.core.logger.qs_logger import get_qs_logger
from cloudshell.shell.core.resource_driver_interface import ResourceDriverInterface
from cloudshell.shell.core.driver_context import InitCommandContext, ResourceCommandContext


class IxiaIxNetworkDriver(ResourceDriverInterface):
    def cleanup(self):
        """
        Destroy the driver session, this function is called everytime a driver instance is destroyed
        This is a good place to close any open sessions, finish writing to log files
        """
        return

    def __init__(self):
        """
        ctor must be without arguments, it is created with reflection at run time
        """
        self.cs_session = None
        self.ixnetwork_session = None
        self.logger = None
        self.reservation_id = None
        self.resource_name = None

        return

    def initialize(self, context):
        """
        Initialize the driver session, this function is called everytime a new instance of the driver is created
        This is a good place to load and cache the driver configuration, initiate sessions etc.
        :param InitCommandContext context: the context the command runs on
        """
        self.logger = get_qs_logger()

        return

    def configure_via_blueprint(self, context):
        self._ixnetwork_session_handler(context)
        license_server = '192.168.41.116'

        root_path = self.ixnetwork_session.getRoot()
        available_hardware_path = root_path + '/availableHardware'
        virtual_chassis_path = available_hardware_path + '/virtualChassis'

        chassis_address = context.resource.address
        chassis = self.ixnetwork_session.add(available_hardware_path, 'chassis')
        self.ixnetwork_session.setAttribute(chassis, '-hostname', chassis_address)
        self.ixnetwork_session.setAttribute(chassis, '-masterChassis', '')
        self.ixnetwork_session.commit()
        try:
            self.ixnetwork_session.execute('connectToChassis', chassis_address)
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Connected to chassis(%s)" %
                                                            (self.resource_name,
                                                             chassis_address))
        except Exception as e:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Failed to connect to chassis(%s), %s:%s" %
                                                            (self.resource_name,
                                                             chassis_address,
                                                             e.__class__.__name__,
                                                             e.message))
            raise

        virtual_chassis = self.ixnetwork_session.getList(available_hardware_path, 'virtualChassis')[0]
        self.ixnetwork_session.setAttribute(virtual_chassis, '-licenseServer', license_server)
        self.ixnetwork_session.commit()
        self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                        "[%s] Set license server to %s" %
                                                        (self.resource_name,
                                                         license_server))

        chassis_cards = ['192.168.41.109', '192.168.41.110']
        for card_number, card_info in enumerate(chassis_cards, start=1):
            card = self.ixnetwork_session.add(virtual_chassis, 'ixVmCard')
            self.ixnetwork_session.setMultiAttribute(card,
                                                     '-managementIp', card_info,
                                                     '-cardId', card_number,
                                                     '-keepAliveTimeout', '300')
            self.ixnetwork_session.commit()
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Added card %s(%s)" %
                                                            (self.resource_name,
                                                             card_number,
                                                             card_info))

            virtual_card = self.ixnetwork_session.getList(virtual_chassis_path, 'ixVmCard')[card_number - 1]
            ports_per_card = 1
            for port in range(1, ports_per_card + 1):
                port_root = self.ixnetwork_session.add(virtual_card, 'ixVmPort')
                self.ixnetwork_session.setMultiAttribute(port_root,
                                                         '-portId', port,
                                                         '-interface', 'eth1',
                                                         '-promiscMode', 'true')
                self.ixnetwork_session.commit()
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] Added port %s to card %s" %
                                                                (self.resource_name,
                                                                 port,
                                                                 card_number))
        return

    def _ixnetwork_session_handler(self, context):
        self._cs_session_handler(context)

        api_address = context.resource.attributes['API Address']
        api_port = context.resource.attributes['API Port']
        api_version = context.resource.attributes['API Version']
        try:
            self.ixnetwork_session = IxNet()
            self.ixnetwork_session.connect(api_address, '-port', api_port, '-version', api_version)
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Using API client v%s at %s:%s" %
                                                            (self.resource_name,
                                                             api_version,
                                                             api_address,
                                                             api_port))
        except Exception as e:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Failed to connect to API client v%s at %s:%s, %s:%s" %
                                                            (self.resource_name,
                                                             api_version,
                                                             api_address,
                                                             api_port,
                                                             e.__class__.__name__,
                                                             e.message))
            raise

        return

    def _cs_session_handler(self, context):
        self.reservation_id = context.reservation.reservation_id
        self.resource_name = context.resource.name

        for attempt in range(3):
            try:
                self.cs_session = CloudShellAPISession(host=context.connectivity.server_address,
                                                       token_id=context.connectivity.admin_auth_token,
                                                       domain=context.reservation.domain)
            except:
                continue
            else:
                break
        else:
            raise

        return
