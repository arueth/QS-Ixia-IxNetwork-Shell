from IxNetwork import IxNet
from cloudshell.api.cloudshell_api import CloudShellAPISession
from cloudshell.core.logger.qs_logger import get_qs_logger
from cloudshell.shell.core.resource_driver_interface import ResourceDriverInterface
from cloudshell.shell.core.driver_context import InitCommandContext, ResourceCommandContext
from collections import OrderedDict


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
        self.cards_in_chassis = 0
        self.chassis_card = {}
        self.reservation_description = None
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

    def add_card(self, context, card_address, num_ports):
        if card_address in self.chassis_card.values():
            existing_card = self.chassis_card.keys()[self.chassis_card.values().index(card_address)]
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "[%s] Card %02d(%s) already exists in the chassis" %
                                                            (self.resource_name,
                                                             existing_card,
                                                             self.chassis_card[existing_card]))
        else:
            self._cs_session_handler(context)
            self._refresh_reservation_details(context)
            self._ixnetwork_session_handler(context)

            root_path = self.ixnetwork_session.getRoot()
            available_hardware_path = root_path + '/availableHardware'
            virtual_chassis_path = available_hardware_path + '/virtualChassis'

            self.cards_in_chassis += 1

            virtual_chassis = self.ixnetwork_session.getList(available_hardware_path, 'virtualChassis')[0]
            try:
                card = self.ixnetwork_session.add(virtual_chassis, 'ixVmCard')
                self.ixnetwork_session.setMultiAttribute(card,
                                                         '-managementIp', card_address,
                                                         '-cardId', self.cards_in_chassis,
                                                         '-keepAliveTimeout', '300')
                self.ixnetwork_session.commit()

                self.chassis_card[self.cards_in_chassis] = card_address
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] Added Card %02d(%s)" %
                                                                (self.resource_name,
                                                                 self.cards_in_chassis,
                                                                 self.chassis_card[self.cards_in_chassis]))
            except Exception as e:
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] Failed to add Card %02d(%s) to chassis, %s:%s" %
                                                                (self.resource_name,
                                                                 self.cards_in_chassis,
                                                                 card_address,
                                                                 e.__class__.__name__,
                                                                 e.message))
                self.cards_in_chassis -= 1

                raise

            current_port = None
            try:
                virtual_card = self.ixnetwork_session.getList(virtual_chassis_path, 'ixVmCard')[
                    self.cards_in_chassis - 1]
                for current_port in range(1, num_ports + 1):
                    port_root = self.ixnetwork_session.add(virtual_card, 'ixVmPort')
                    self.ixnetwork_session.setMultiAttribute(port_root,
                                                             '-portId', current_port,
                                                             '-interface', 'eth1',
                                                             '-promiscMode', 'true')
                    self.ixnetwork_session.commit()
                    self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                    "[%s] Added Port %02d to Card %02d" %
                                                                    (self.resource_name,
                                                                     current_port,
                                                                     self.cards_in_chassis))
            except Exception as e:
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] Failed to add Port %02d to Card %02d, %s:%s" %
                                                                (self.resource_name,
                                                                 current_port,
                                                                 self.cards_in_chassis,
                                                                 e.__class__.__name__,
                                                                 e.message))
                raise

        return

    def add_chassis(self, context, chassis_address):
        self._cs_session_handler(context)
        self._refresh_reservation_details(context)
        self._ixnetwork_session_handler(context)

        root_path = self.ixnetwork_session.getRoot()
        available_hardware_path = root_path + '/availableHardware'

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

        return

    def configure_via_sandbox(self, context):
        self._cs_session_handler(context)
        self._refresh_reservation_details(context)
        self._ixnetwork_session_handler(context)

        chassis = self.resource['Ixia Virtual Application']['Ixia IxVM Chassis']
        if len(chassis) != 1:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "%s chassis found, current implementation only supports one" %
                                                            len(chassis))
            return

        license_server = self.resource['Ixia Application']['Ixia License Server']
        if len(license_server) != 1:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "%s license servers found, current implementation only supports one" %
                                                            len(license_server))
            return

        card = OrderedDict(sorted(self.resource['Ixia Virtual Application']['Ixia IxVM Card'].items()))
        if len(card) == 0:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "No cards found, at least one is required")
            return

        chassis_name, chassis_resource = chassis.popitem()
        self.add_chassis(context, chassis_resource.FullAddress)

        license_server_name, license_server_resource = license_server.popitem()
        self.set_license_server(context, license_server_resource.FullAddress)

        for card_name, card_resource in card.iteritems():
            self.add_card(context, card_resource.FullAddress, 1)
        return

    def set_license_server(self, context, license_server_address):
        self._cs_session_handler(context)
        self._refresh_reservation_details(context)
        self._ixnetwork_session_handler(context)

        root_path = self.ixnetwork_session.getRoot()
        available_hardware_path = root_path + '/availableHardware'

        virtual_chassis = self.ixnetwork_session.getList(available_hardware_path, 'virtualChassis')[0]
        self.ixnetwork_session.setAttribute(virtual_chassis, '-licenseServer', license_server_address)
        self.ixnetwork_session.commit()
        self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                        "[%s] Set license server to %s" %
                                                        (self.resource_name,
                                                         license_server_address))

        return

    def teardown(self, context):
        self._cs_session_handler(context)
        self._refresh_reservation_details(context)
        self._ixnetwork_session_handler(context)

        self.ixnetwork_session.disconnect()

        return

    def _ixnetwork_session_handler(self, context):
        try:
            self.ixnetwork_session.getVersion()
        except (AttributeError, Exception) as e:
            if e.__class__ != AttributeError:
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] _ixnetwork_session_handler %s:%s" %
                                                                (self.resource_name,
                                                                 e.__class__.__name__,
                                                                 e.message))

            utility_server_name, utility_server_resource = self.utility_server.popitem()
            api_address = utility_server_resource.FullAddress
            api_port = context.resource.attributes['API Port']
            api_version = context.resource.attributes['API Version']
            try:
                self.ixnetwork_session = IxNet()
                self.ixnetwork_session.connect(api_address, '-port', api_port, '-version', api_version)
                self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                                "[%s] Connected to API v%s at %s:%s" %
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

    def _refresh_reservation_details(self, context):
        self.reservation_id = context.reservation.reservation_id
        self.reservation_description = self.cs_session.GetReservationDetails(self.reservation_id).ReservationDescription
        self.resource = self._covert_reservation_resources()

        self.utility_server = {}
        if 'Ixia Virtual Application' in self.resource:
            self.utility_server.update(self.resource['Ixia Virtual Application'].get('Ixia IxVM Utility Server', {}))

        if 'Ixia Application' in self.resource:
            self.utility_server.update(self.resource['Ixia Application'].get('Ixia Utility Server', {}))

        if len(self.utility_server) != 1:
            self.cs_session.WriteMessageToReservationOutput(self.reservation_id,
                                                            "%s utility servers found, current implementation requires one" %
                                                            len(self.utility_server))
            return

        return

    def _covert_reservation_resources(self):
        dictionary = {}
        for resource in self.reservation_description.Resources:
            if resource.ResourceFamilyName not in dictionary:
                dictionary[resource.ResourceFamilyName] = {}

            if resource.ResourceModelName not in dictionary[resource.ResourceFamilyName]:
                dictionary[resource.ResourceFamilyName][resource.ResourceModelName] = {}

            dictionary[resource.ResourceFamilyName][resource.ResourceModelName][resource.Name] = resource

        return dictionary

    def _cs_session_handler(self, context):
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
