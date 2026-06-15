''' Abstract class containing general methods for any instrument interface'''
''' Note: most of docstrings in this file have been generated automatically by Claude. AI can make mistakes'''
import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as Qt# QApplication, QWidget, QMainWindow, QPushButton, QHBoxLayout
import PyQt5.QtGui as QtGui
import logging
import json
import os
import importlib
#import traceback

graphics_dir = os.path.join(os.path.dirname(__file__), 'graphics')

class abstract_interface(QtCore.QObject):
    """
        Abstract class for high-level interface with devices
        ...

        Attributes
        ----------
        settings : dict
            settings of this interface (typically loaded from a .json file or set in the __init__ method of the instance)
        output : dict
            a dictionary containing the output data created by this interface
        app : Qt.QApplication
            The pyqt5 QApplication() object
        verbose : bool          defined as @property, can be read and written
            Set whether the logger of this interface will be verbose or not (default = True)
        name_logger : str       defined as @property, can be read and written
            Name of the logger of this interface (default = __package__). The logger formatter will be "[name_logger]:...".

        Methods
        -------

        load_settings(dictionary)

        save_settings()
                
        set_disconnected_state()

        set_connecting_state()

        set_connected_state()

        set_trigger(external_function,delay=0)
            Set this device as a trigger for other operations. Every time that this interface object acquires data from the device (i.e. every time 
            the function self.update is executed), the function external_function, passed as input parameter, is also called. 
            external_function must be a valid function which does not require any input parameter.
            The optional parameter delay sets a delay (in seconds) between the call to the function self.update and the call to the function external_function
            When external_function is set to None, the trigger is effectively disabled.

        send_trigger

        _send_trigger

        update()

        check_property_until(self, property_to_check, values_list, actions_list, refresh_time=0.1)

        close()
            Closes this interface, disconnect device (if any) and close plot window

    """

    output = dict()
    settings = dict()
    ## SIGNALS THAT WILL BE USED TO COMMUNICATE WITH THE GUI
    sig_connected = QtCore.pyqtSignal(int) 
    sig_close = QtCore.pyqtSignal()
    # Identifier codes used for view-model communication
    SIG_CONNECTED = 1
    SIG_CONNECTING = 2
    SIG_DISCONNECTED = 3
    SIG_DISCONNECTING = 4
    
    def __init__(self, app, name_logger=None, config_dict=None, **kwargs):
        """
        Parameters
        ----------
        app : Qt.QApplication
            The PyQt5 QApplication object shared by the whole program.
        name_logger : str, optional
            Name to assign to this interface's logger. If not specified (default), the
            name of the package of the child class is used (retrieved automatically via
            ``importlib``).
        config_dict : dict, optional
            Dictionary of settings to load via :meth:`load_settings`. If not specified
            (default), settings are instead loaded from a ``config.json`` file located
            in the same folder as the child class module, if such a file exists and can
            be parsed.
        **kwargs
            Additional keyword arguments. Not used directly by this base class, but
            accepted so that subclasses can forward extra parameters without causing
            a ``TypeError``.
        """
        self.app = app
        self._verbose = True            #Keep track of whether this instance of the interface should produce logs or not

        if name_logger == None:
            name_logger = importlib.import_module(self.__module__).__package__    # Use importlib to retrieve the name of the package which is using this abstract class

        self.name_logger = name_logger #Setting this property will also create the logger,set the default output style, and store the logger object in self.logger   
        m = importlib.import_module(self.__module__)    # Use importlib to retrieve path of child class
        folder_package = os.path.dirname(os.path.abspath(m.__file__))
        self.config_file = os.path.join(folder_package,'config.json')
        if not config_dict: #If the dictionary config was not specified as input, we check if there is a config.json file in the package folder, and load that
            #we load its keys-values as properties of this object
            try:
                self.logger.info(f"Loading settings for this device from the file \'{self.config_file}\'...")
                with open(self.config_file) as jsonfile:
                    config_dict = json.load(jsonfile)
            except Exception as e:
                self.logger.info(f"Error when loading file \'{self.config_file}\': {e}.")
                pass
        if config_dict:
            self.load_settings(config_dict)
        QtCore.QObject.__init__(self)

    @property
    def verbose(self):
        '''
        bool: Whether this interface's logger is verbose (``True``) or not (``False``).

        When set to ``True``, the logger level is set to ``logging.INFO``. When set to
        ``False``, the logger level is set to ``logging.CRITICAL`` (effectively
        silencing ``info``-level messages).
        '''
        return self._verbose

    @verbose.setter
    def verbose(self,verbose):
        self._verbose = verbose
        #When the verbose property of this interface is changed, we also update accordingly the level of the logger object
        if verbose: loglevel = logging.INFO
        else: loglevel = logging.CRITICAL
        self.logger.setLevel(level=loglevel)

    @property
    def name_logger(self):
        '''
        str: The name of this interface's logger.

        Setting this property creates (or retrieves) a ``logging.Logger`` with the
        given name, stores it in :attr:`logger`, attaches a ``StreamHandler`` with the
        format ``"[name_logger]: %(message)s"`` (only if the logger does not already
        have handlers), sets ``propagate = False``, and applies the current
        :attr:`verbose` setting to the logger's level.
        '''
        return self._name_logger

    @name_logger.setter
    def name_logger(self,name):
        #Create logger, and set default output style.
        self._name_logger = name
        self.logger = logging.getLogger(self._name_logger)
        self.verbose = self._verbose #This will automatically set the logger verbosity too
        if not self.logger.handlers:
            formatter = logging.Formatter(f"[{self.name_logger}]: %(message)s")
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)
        self.logger.propagate = False

    def read_current_output(self):
        '''
        Returns
        -------
        dict
            The current contents of :attr:`output`, i.e. the most recently produced
            output data of this interface.
        '''
        return self.output

    def load_settings(self,dictionary):
        '''
        Merge the given dictionary into :attr:`settings`.

        Parameters
        ----------
        dictionary : dict
            Settings to merge into :attr:`settings` (via ``dict.update``). Keys already
            present in :attr:`settings` are overwritten; keys not already present are
            added.
        '''
        self.settings.update(dictionary)

    def save_settings(self):
        '''
        Write the current contents of :attr:`settings` to :attr:`config_file` as
        indented, alphabetically-sorted JSON.

        If an error occurs while writing the file (e.g. the file is not writable),
        the error is logged via :attr:`logger` and otherwise ignored.
        '''
        if self.config_file:
            self.logger.info(f"Storing current settings for this device into the file \'{self.config_file}\'...")
            try:
                with open(self.config_file, 'w') as fp:
                    json.dump(self.settings, fp, indent=4, sort_keys=True)
            except Exception as e:
                self.logger.error(f"An error occurred while saving settings in the config.json file: {e}")
                
    def set_disconnecting_state(self):
        '''
        Emit :attr:`sig_connected` with the value :attr:`SIG_DISCONNECTING`, to notify
        that disconnection from the device is in progress.
        '''
        self.sig_connected.emit(self.SIG_DISCONNECTING)

    def set_disconnected_state(self):
        '''
        Emit :attr:`sig_connected` with the value :attr:`SIG_DISCONNECTED`, to notify
        that the device is currently disconnected.
        '''
        self.sig_connected.emit(self.SIG_DISCONNECTED)

    def set_connecting_state(self):
        '''
        Emit :attr:`sig_connected` with the value :attr:`SIG_CONNECTING`, to notify
        that connection to the device is in progress.
        '''
        self.sig_connected.emit(self.SIG_CONNECTING)

    def set_connected_state(self):
        '''
        Emit :attr:`sig_connected` with the value :attr:`SIG_CONNECTED`, to notify
        that the device is currently connected.
        '''
        self.sig_connected.emit(self.SIG_CONNECTED)

    def set_trigger(self,external_function,delay=0):
        '''
        This method allows to use this device as a trigger for other operations. Every time that this interface object acquires data from the device (i.e. every time 
        the function self.update is executed), the function external_function is also called. external_function must be a valid function which does not 
        require any input parameter.
        The optional parameter delay sets a delay (in seconds) between the call to the function update and the call to the function external_function
        When external_function is set to None, the trigger is effectively disabled.

        Parameters
        ----------
        external_function : callable or None
            Function (taking no input parameters) to call every time :meth:`update` is
            executed. If ``None``, any existing trigger is disabled.
        delay : float, optional
            Delay (in seconds) between the call to :meth:`update` and the call to
            ``external_function`` (default = 0, i.e. no delay). Must be a
            non-negative number.

        Notes
        -----
        If ``external_function`` is not callable, or ``delay`` is not a valid
        non-negative number, an error is logged via :attr:`logger` and no trigger is
        configured (or the existing one is left unchanged).
        '''
        if external_function == None:
            self.trigger = None
            return
        if not(callable(external_function)):
            self.logger.error(f"Input parameter external_function must be a valid function")  
            return  
        try:
            delay = float(delay)
            if delay < 0:
                raise ValueError()
        except (TypeError,ValueError):
            self.logger.error(f"Input parameter delay must be a valid and positive number.")  
        self.logger.info(f"Creating a trigger for this device...")
        self.trigger = [external_function, delay]

    def send_trigger(self):
        '''
        Fire the trigger configured via :meth:`set_trigger`.

        If the configured delay (``self.trigger[1]``) is greater than zero, the call to
        :meth:`_send_trigger` is scheduled after that delay (in seconds) using
        ``QtCore.QTimer.singleShot``. Otherwise, :meth:`_send_trigger` is called
        immediately.

        Notes
        -----
        This method assumes that :attr:`trigger` has been set to a valid
        ``[external_function, delay]`` pair (i.e. that :meth:`set_trigger` was called
        with a callable ``external_function``). It is normally called automatically by
        :meth:`update`.
        '''
        if(self.trigger[1])>0:
            self.logger.info(f"Trigger will be sent in {self.trigger[1]} seconds.")
            QtCore.QTimer.singleShot(int(self.trigger[1]*1e3), self._send_trigger)
        else:
            self._send_trigger()

    def _send_trigger(self):
        '''
        Call the trigger function configured via :meth:`set_trigger` (i.e.
        ``self.trigger[0]()``), and log that the trigger was sent.
        '''
        self.logger.info(f"Trigger sent.")
        self.trigger[0]()

    def receive_trigger(self,**kwargs):
        '''
        This method allows the device to receive a trigger from an external script (for example, when the device is used inside Ergastirio). 
        The function defined here in the abstract_interface class is just a placeholder. The specific action that happens when the instrument
        is triggered will be coded in the corresponding child class of the instrument interface
        '''
        pass

    def update(self):
        '''
        If a trigger has been configured via :meth:`set_trigger` (i.e. :attr:`trigger`
        is defined and is not ``None``), call :meth:`send_trigger` to fire it.

        This method is meant to be called by subclasses (via ``super().update()``)
        every time new data has been acquired from the device, so that any configured
        trigger fires in sync with data acquisition.
        '''
        if hasattr(self,'trigger'):
            if not(self.trigger==None):
                self.send_trigger()
                
    @staticmethod
    def check_property_until(property_to_check, values_list, actions_list, refresh_time=0.1):
        '''
        property_to_check: function that takes no parameter in input
            Property whose value will be periodically checked
        values_list : list
            List of possible values to be checked
        actions_list : list of list of functions, 
            The format must be actions_list = [ [Value1Func1, Value1Func2, ...], [Value2Func1, Value2Func2, ...], ... , [ValueNFunc1, ValueNFunc2, ...] ]
        refresh_time: float (default = 0.01) 
            Set the time interval (in s) after which the value of property_to_check will be checked again

        It periodically evaluates the value returned by the function property_to_check. 
        - If property_to_check() is equal to values_list[i], it performs all the actions defined in the list actions_list[i] (which is a list of functions). 
        It then calls itself again after a time defined by refresh_time, unless values_list[i] is the last object of the list values_list. In this case it does
        not call itself again
        - If the value of property_to_check() is not in values_list, it calls itself again after a time defined by refresh_time, but without performing any action

        Example
            def foo_test():
                return True

            values_list = [1,True,'a']
            actions_list = [ [foo1, foo2, foo3],    [], [foo4] ]
            
            check_property_until( property_to_check = foo_test, values_list, actions_list)

        '''
        call_again = True
        for index,value in enumerate(values_list):
            #try:
            #print(property_to_check())
            if property_to_check() == value:
                for action in actions_list[index]:
                    action()
                if index == (len(values_list) - 1):
                    call_again  = False
            #except Exception as e:
            #    self.logger.error(f"{e}")
        
        if call_again:
            QtCore.QTimer.singleShot(int(refresh_time*1e3), lambda :  abstract_interface.check_property_until(property_to_check, values_list, actions_list, refresh_time))
            
    def close(self):     
        '''
        Close this interface.

        Emits :attr:`sig_close`, saves the current settings via :meth:`save_settings`,
        and, if this interface has an :attr:`instrument` attribute and it is currently
        connected, disconnects it by calling ``self.disconnect_device()``. Any
        exception raised while disconnecting is caught and logged via
        :attr:`logger`, rather than propagated.
        '''
        self.sig_close.emit()
        self.save_settings()
        if hasattr(self, "instrument"):
            try:
                if (self.instrument.connected == True):
                    self.disconnect_device()
            except Exception as e:
                self.logger.error(f"{e}")
        
class abstract_gui():
    def __init__(self,interface=None,parent=None):
        """
        Parameters
        ----------
        interface : abstract_interface or None
            Instance of the interface (model) class that this GUI controls.
        parent : Qt.QWidget or None
            Qt widget that will host this GUI. Its layout will be set to
            ``self.container`` when :meth:`initialize` is called.
        """
        self.interface = interface
        self.parent = parent

    def initialize(self):
        '''
        Finalize the GUI by assigning the layout built by ``create_widgets()`` to the
        parent widget, and resizing the parent widget to its minimum size.

        ``self.container`` (a layout object: either ``QVBoxLayout``, ``QHBoxLayout``,
        or ``QGroupBox``) must be created beforehand by the ``create_widgets()`` method
        of the child GUI class.

        Raises
        ------
        RuntimeError
            If ``self.container`` has not been set, i.e. if ``create_widgets()`` was
            not called before this method.
        '''
        #self.container is a layout object (either QVBoxLayout,QHBoxLayout or QGroupBox) which is created in the create_widgets() method of the child GUI class
        if not hasattr(self, 'container'): raise RuntimeError("create_widgets() must be called before initialize()")
        self.parent.setLayout(self.container) 
        self.parent.resize(self.parent.minimumSize())
        return

    def disable_widget(self,widgets):
        '''
        Disable a collection of Qt widgets.

        Parameters
        ----------
        widgets : iterable of Qt.QWidget or None
            Widgets to disable, by calling ``widget.setEnabled(False)``. Entries that
            are falsy (e.g. ``None``) are silently skipped.
        '''
        for widget in widgets:
            if widget:
                widget.setEnabled(False)   

    def enable_widget(self,widgets):
        '''
        Enable a collection of Qt widgets.

        Parameters
        ----------
        widgets : iterable of Qt.QWidget or None
            Widgets to enable, by calling ``widget.setEnabled(True)``. Entries that
            are falsy (e.g. ``None``) are silently skipped.
        '''
        for widget in widgets:
            if widget:
                widget.setEnabled(True) 

    def create_panel_connection_listdevices(self):
        """
        Many instruments require a similar part of the GUI: a row having a button for connection/disconnection, a combobox to list available devices, and a button to refresh the list of 
        available devices. To avoid repeating code, we define here a method which creates this general part of the GUI

        Returns
        -------
         Qt.QHBoxLayout
            A horizontal box layout containing the relevant GUI
        dict
            Dictionary, the keys are the names of the widgets, the values are the widgets
        """
        hbox_panel_connection_listdevices = Qt.QHBoxLayout()
        button_ConnectDevice = Qt.QPushButton("Connect")
        label_DeviceList = Qt.QLabel("Devices: ")
        combo_Devices = Qt.QComboBox()
        button_RefreshDeviceList = Qt.QPushButton("")
        button_RefreshDeviceList.setIcon(QtGui.QIcon(os.path.join(graphics_dir,'refresh.png')))     
        widgets_dict = {'button_ConnectDevice':button_ConnectDevice,
                        'label_DeviceList':label_DeviceList,
                        'button_RefreshDeviceList':button_RefreshDeviceList,
                        'combo_Devices':combo_Devices}
        widgets_stretches = [0,0,0,1]
        for w,s in zip(widgets_dict.values(),widgets_stretches):
            hbox_panel_connection_listdevices.addWidget(w,stretch=s)
        return hbox_panel_connection_listdevices, widgets_dict