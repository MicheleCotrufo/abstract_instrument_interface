from abstract_instrument_interface import abstract_classes
import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as Qt# QApplication, QWidget, QMainWindow, QPushButton, QHBoxLayout
import PyQt5.QtGui as QtGui
import logging

class ramp(QtCore.QObject):
    """
    Many instruments require having a ramp panel in their GUI, which allows sweeping a certain
    parameter and sending a trigger. This class generates a general "ramp panel", which can then
    be customized by the child instance, and contains the minimal logic to perform a ramp.
    It inherits from QtCore.QObject and uses methods from abstract_interface via composition
    (through the interface object passed to its constructor).

    Important: the interface object that instantiates this ramp() object needs to have some
    QtCore.pyqtSignal objects defined as attributes, in order to communicate with this ramp() object.

    Signals that need to be defined as attributes of self.interface, together with their flags:

    +------------------------------------------+---------------------------------------------+---------------------------------------------------------------------------------------------+
    | Signal                                   | Triggered when ...                          | Parameter sent                                                                              |
    +==========================================+=============================================+=============================================================================================+
    | sig_connected = pyqtSignal(int)          | The connection status of interface changed  | SIG_CONNECTED, SIG_DISCONNECTED, SIG_CONNECTING, SIG_DISCONNECTING                         |
    +------------------------------------------+---------------------------------------------+---------------------------------------------------------------------------------------------+
    | sig_change_moving_status = pyqtSignal(int) | The movement status of interface changed  | SIG_MOVEMENT_STARTED, SIG_MOVEMENT_ENDED                                                    |
    +------------------------------------------+---------------------------------------------+---------------------------------------------------------------------------------------------+

    The interface will emit these signals to notify of changes.
    """
    
    # Identifier codes used for view-model communication. Other general-purpose codes are specified in abstract_instrument_interface
    SIG_RAMP_STARTED = 1
    SIG_RAMP_STEP_STARTED = 3
    SIG_RAMP_STEP_ENDED = 4
    SIG_RAMP_TRIGGER_FIRED = 5
    SIG_RAMP_ENDED = 2
    
    ## SIGNALS THAT WILL BE USED TO COMMUNICATE WITH THE GUI
    #                                                           | Triggered when ...                                                                | Sends as parameter    
    #                                                       #   -----------------------------------------------------------------------------------------------------------------------         
    sig_ramp = QtCore.pyqtSignal(int)                       #   | Ramp event                                                                        | One of the identifiers SIG_RAMP_STARTED, SIG_RAMP_STEP_STARTED, SIG_RAMP_STEP_ENDED, etc.
    sig_ramp_settings = QtCore.pyqtSignal(dict)             #   | One of the settings changed, or when the GUI requested it                         |
    sig_ramp_info = QtCore.pyqtSignal(list)                 #   | General info released by the model, typically used in a status label in the GUI   |

    def __init__(self, interface):
        '''
        Parameters
        ----------
        interface : object
            The interface object that owns this ramp. Must define ``logger``, the
            QtCore.pyqtSignal attributes documented in the class docstring, and (after
            calling :meth:`set_ramp_functions`) the callback functions used to perform
            the ramp.

        Attributes
        ----------
        settings : dict
            Default values of the ramp settings (may be overridden later by values loaded
            from a config file). Keys are:

            ``ramp_step_size`` : float
                Increment value applied at each ramp step.
            ``ramp_wait_1`` : float
                Wait time (in s) after each ramp step (i.e. after each "move").
            ``ramp_send_trigger`` : bool
                If ``True``, ``func_trigger`` is called after each step (following ``ramp_wait_1``).
            ``ramp_wait_2`` : float
                Wait time (in s) after each (potential) trigger, before the next ramp step.
            ``ramp_numb_steps`` : int (positive)
                Number of steps in the ramp.
            ``ramp_repeat`` : int (positive)
                How many times the whole ramp sequence is repeated.
            ``ramp_reverse`` : bool
                If ``True``, the ramp is repeated in reverse direction after the forward sweep.
            ``ramp_send_initial_trigger`` : bool
                If ``True``, ``func_trigger`` is called once before the ramp starts.
            ``ramp_reset`` : bool
                If ``True``, the controlled parameter is reset to its pre-ramp value once the
                ramp has finished.
        '''
        #super().__init__(app=interface.app)
        super().__init__()
        self.interface = interface          #Interface object which is using this ramp object
        self.logger = self.interface.logger
        self.doing_ramp = False             #Flag variable used to keep track of when a ramp is being done
        self.settings = {                   ### Default values of settings (may be overridden by settings saved in .json files later)
            'ramp_step_size': 1,            #Increment value of each ramp step
            'ramp_wait_1': 1,               #Wait time (in s) after each ramp step
            'ramp_send_trigger' : True,     #If true, the function self.func_trigger is called after each 'movement'
            'ramp_wait_2': 1,               #Wait time (in s) after each (potential) call to trigger, before doing the new ramp step
            'ramp_numb_steps': 10,          #Number of steps in the ramp
            'ramp_repeat': 1,               #How many times the ramp is repeated
            'ramp_reverse': 1,              #If True (or 1), it repeats the ramp in reverse
            'ramp_send_initial_trigger': 1, #If True (or 1), it calls self.func_trigger before starting the ramp
            'ramp_reset' : 1                #If True (or 1), it resets the value of the instrument to the initial one after the ramp is done
             }
        self.numb_steps_done = 0            #Internal variable used to keep track of how many ramp steps have been already performed (Note: here ramp step means only changing a certain parameter, not waiting or sending triggers)
        self.numb_steps_total = 0           #Internal variable used to keep track of how many ramp steps there are in total (Note: here ramp step means only changing a certain parameter, not waiting or sending triggers)
        self.has_child_ramp = False
        self.has_parent_ramp = False
        self.child_ramp = None
        self.parent_ramp = None
        self.id = id(self)
        
    def set_ramp_functions(self,    func_move, 
                                    func_check_step_has_ended, 
                                    func_trigger = None, 
                                    func_trigger_continue_ramp = None,
                                    func_set_value = None, 
                                    func_read_current_value = None, 
                                    list_functions_step_not_ended=None,  
                                    list_functions_step_has_ended=None,
                                    list_functions_ramp_started=None,
                                    list_functions_ramp_ended =None):
        '''
        Parameters
        ----------
        func_move : callable
            Function that must accept a single parameter as input: the amount by which the
            instrument "moves" (i.e. the signed step size).
        func_check_step_has_ended : callable
            Function that takes no parameters and returns ``True`` when the step has ended,
            ``False`` otherwise.
        func_trigger : callable or None, optional
            Function that takes no parameters. Called after each ramp step (if
            ``ramp_send_trigger`` is set) and/or before the ramp starts (if
            ``ramp_send_initial_trigger`` is set). Set to ``None`` to disable.
        func_trigger_continue_ramp : callable or None, optional
            Function that takes no parameters. If not ``None``, after ``func_trigger`` is
            invoked, the ramp will wait until ``func_trigger_continue_ramp()`` returns
            ``True`` before executing the next ramp step. Note: this waiting time adds up
            to the time already set by ``ramp_wait_1`` and ``ramp_wait_2``.
        func_set_value : callable or None, optional
            Function that sets the instrument to a given value. Used to restore the
            pre-ramp value if ``ramp_reset`` is enabled. Can be ``None``.
        func_read_current_value : callable or None, optional
            Function that takes no parameters and returns the current value of the
            instrument. Used to record the pre-ramp value for ``ramp_reset``. Can be
            ``None``.
        list_functions_step_not_ended : list of callable, optional
            Functions that take no parameters. When doing a ramp, after each step is
            executed, the step completion is checked periodically. Each time the step has
            not yet ended, all functions in this list are called.
        list_functions_step_has_ended : list of callable, optional
            Functions that take no parameters. When doing a ramp, after each step is
            executed, the step completion is checked periodically. When the step has ended,
            all functions in this list are called.
        list_functions_ramp_started : list of callable, optional
            Functions that take no parameters. They are all called once when the ramp starts.
        list_functions_ramp_ended : list of callable, optional
            Functions that take no parameters. They are all called once when the ramp ends.
        '''
        self.func_move = func_move
        self.func_trigger = func_trigger
        self.func_trigger_continue_ramp = func_trigger_continue_ramp
        self.func_set_value = func_set_value      # This and next function are useful for resetting the instrument back to its original position. They can be set to none.
        self.func_read_current_value = func_read_current_value  
        self.func_check_step_has_ended = func_check_step_has_ended
        self.list_functions_step_not_ended = list_functions_step_not_ended or []
        self.list_functions_step_has_ended = list_functions_step_has_ended or []
        self.list_functions_ramp_started = list_functions_ramp_started or []
        self.list_functions_ramp_ended = list_functions_ramp_ended or []

    def set_ramp_settings(self,settings):
        '''
        Merge the given dictionary into :attr:`settings` via ``dict.update``.

        Parameters
        ----------
        settings : dict
            Dictionary of ramp settings to apply. Keys not present in the existing
            :attr:`settings` are added; existing keys are overwritten. No validation
            is performed — use :meth:`set_setting` for validated, per-key updates.
        '''
        self.settings.update(settings)
    
    def set_setting(self,setting_name,setting_value,log=True):
        '''
        Validate and apply a single ramp setting.

        Settings are grouped by type and allowed value range:

        - ``ramp_step_size``: float, strictly positive.
        - ``ramp_wait_1``, ``ramp_wait_2``: float, non-negative.
        - ``ramp_send_initial_trigger``, ``ramp_send_trigger``, ``ramp_reverse``,
          ``ramp_reset``: boolean-like (``True``, ``False``, ``0``, ``1``,
          ``'0'``, ``'1'``, ``'true'``, ``'false'``).
        - ``ramp_numb_steps``, ``ramp_repeat``: integer, strictly positive.

        If validation passes and the new value differs from the current one, the
        setting is updated, optionally logged, and :meth:`send_settings` is emitted.
        If validation fails, :meth:`send_settings` is emitted anyway so the GUI can
        revert the widget to the current (unchanged) value.

        Parameters
        ----------
        setting_name : str
            Name of the setting to update (must be a key of :attr:`settings`).
        setting_value : any
            Proposed new value. Will be cast to the appropriate type if valid.
        log : bool, optional
            If ``True`` (default), log the new value via :attr:`logger` when the
            update is successful.

        Returns
        -------
        any
            The current (post-update, or unchanged-if-invalid) value of the setting.
        '''
        flag_succesful = False
        flag_emit_current_settings = False
        if setting_name == 'ramp_step_size':                                                                #float, positive
            try: 
                setting_value = float(setting_value)
                if setting_value <= 0:
                    raise ValueError
                flag_succesful = True
            except ValueError:
                self.logger.error(f"Ramp step size must be a valid and positive number.")
                flag_emit_current_settings = True
        if setting_name in ['ramp_wait_1' ,'ramp_wait_2']:                                                  #float, non-negative
            try: 
                setting_value = float(setting_value)
                if setting_value < 0:
                    raise ValueError
                flag_succesful = True
            except ValueError:
                self.logger.error(f"{setting_name} must be a valid and non-negative number.")
                flag_emit_current_settings = True
        if setting_name in ['ramp_send_initial_trigger','ramp_send_trigger','ramp_reverse','ramp_reset']:   #boolean
            if setting_value not in (True, False, 0, 1, '0', '1', 'true', 'false'):
                self.logger.error(f"{setting_name} must be a boolean(-like) variable.")
                lag_emit_current_settings = True
            else:
                setting_value = bool(setting_value)
                flag_succesful = True
        if setting_name in ['ramp_numb_steps','ramp_repeat']:                                               #integer, positive
            try: 
                setting_value = int(setting_value)
                if setting_value <= 0:
                    raise ValueError
                flag_succesful = True
            except ValueError:
                self.logger.error(f"{setting_name} must be a positive integer.")
                flag_emit_current_settings = True
                
        if self.settings[setting_name] == setting_value:
            flag_succesful = False
        if flag_succesful:
            self.settings[setting_name] = setting_value
            if log:
                self.logger.info(f"{setting_name} is now set to {setting_value}.")
            self.send_settings()
        if flag_emit_current_settings:
            self.send_settings()
        return self.settings[setting_name]
    
    def send_settings(self):
        '''
        Emit :attr:`sig_ramp_settings` with the current :attr:`settings` dictionary,
        so that the GUI can update its widgets to reflect the current state.
        '''
        self.sig_ramp_settings.emit(self.settings)
        
    def send_ramp_status(self):
        '''
        Uses the sig_ramp_info signal to emit a text string with info on the current ramp status
        '''
        info_ramp_status = ''
        info_ramp_connection = ''

        if self.doing_ramp == False:
            info_ramp_status = f"<b><font color=\"Red\">Ramp off</font></b>"
        if self.doing_ramp == True:
            info_ramp_status = f"<b><font color=\"Green\">Doing ramp (step = {self.numb_steps_done}/{self.numb_steps_total})</font></b>"

        if self.has_child_ramp:
            info_ramp_connection = f"<b><font color=\"Blue\">Connected to child (id = {str(self.child_ramp.id)})</font></b>"

        if self.has_parent_ramp:
            info_ramp_connection = f"<b><font color=\"Blue\">Connected to parent (id = {str(self.parent_ramp.id)})</font></b>"

        self.sig_ramp_info.emit([info_ramp_status, info_ramp_connection])
        
    def start_ramp(self, *args, **kwargs):
        '''
        Read the current ramp settings, build the corresponding action sequence via
        :meth:`generate_list_actions`, and begin executing it.

        If ``ramp_reset`` is enabled and ``func_read_current_value`` is set, the
        current value of the controlled parameter is recorded before the ramp starts,
        so it can be restored at the end.

        Emits :attr:`sig_ramp` with :attr:`SIG_RAMP_STARTED`, then runs all callbacks
        in ``list_functions_ramp_started``, before the first action is executed.

        Parameters
        ----------
        *args, **kwargs
            Accepted for compatibility (e.g. when this method is used as a trigger
            callback by a parent ramp via :meth:`connect_to_ramp_child`), but not used.
        '''
        initial_trigger = self.settings['ramp_send_initial_trigger']
        stepsize = self.settings['ramp_step_size']
        wait1 = self.settings['ramp_wait_1'] 
        send_trigger = self.settings['ramp_send_trigger'] 
        wait2 = self.settings['ramp_wait_2'] 
        numb_steps = self.settings['ramp_numb_steps']
        add_reverse = self.settings['ramp_reverse']
        repeat_ramp = self.settings['ramp_repeat']
        reset_after_ramp = self.settings['ramp_reset']
        
        actions = self.generate_list_actions(initial_trigger, stepsize, wait1, send_trigger, wait2, numb_steps, add_reverse , repeat_ramp, reset_after_ramp)
        self.numb_steps_total = sum([ 1 for action in actions if action['action'] == 'move'])
        self.numb_steps_done = 0
        if reset_after_ramp and self.func_read_current_value:
            self.initial_value = self.func_read_current_value()
        self.logger.info(f"Starting ramp...")
        self.sig_ramp.emit(self.SIG_RAMP_STARTED)
        for action in self.list_functions_ramp_started:
            action() 
        self.doing_ramp = True
        self.run_sequence(actions)
        
    def reset_to_initial_value(self):
        '''
        Reset the controlled parameter to the value it had before the ramp started.

        Only acts if both ``func_set_value`` is set and ``initial_value`` was recorded
        (i.e. :meth:`start_ramp` was called with ``ramp_reset`` enabled and
        ``func_read_current_value`` available). Any exception raised by
        ``func_set_value`` is silently ignored.
        '''
        if self.func_set_value and hasattr(self,'initial_value'):
            try:
                self.logger.info(f"Resetting ramp parameter to original value = {self.initial_value}...")
                self.func_set_value(self.initial_value)    
            except:
                pass
        return
    
    def is_doing_ramp(self):
        '''
        Returns
        -------
        bool
            ``True`` if a ramp is currently in progress, ``False`` otherwise.
        '''
        return self.doing_ramp

    def is_not_doing_ramp(self):
        '''
        Returns
        -------
        bool
            ``True`` if no ramp is currently in progress, ``False`` otherwise.
            Convenience complement of :meth:`is_doing_ramp`, used as a
            ``func_trigger_continue_ramp`` callback when chaining ramps via
            :meth:`connect_to_ramp_child`.
        '''
        return not(self.is_doing_ramp())
    
    def stop_ramp(self):
        '''
        Stop the ramp currently in progress, if any.

        If a ramp is running (``self.doing_ramp == True``), calls
        :meth:`ramp_ended` with ``by_user=True``. Has no effect if no ramp is
        currently running.
        '''
        if self.doing_ramp == True:
            self.ramp_ended(by_user = True)
        
    def run_sequence(self,sequence):
        '''
        Store the given action sequence and begin executing it from the first action.

        Parameters
        ----------
        sequence : list of dict
            The ordered list of actions produced by :meth:`generate_list_actions`.
            Each element is a dict with at least an ``'action'`` key.
        '''
        self.sequence = sequence
        self._run_sequence(0)
        
    def ramp_ended(self,by_user = False):
        '''
        Mark the ramp as finished and clean up.

        Sets ``doing_ramp`` to ``False``, emits :attr:`sig_ramp` with
        :attr:`SIG_RAMP_ENDED`, logs a message, runs all callbacks in
        ``list_functions_ramp_ended``, and calls :meth:`send_ramp_status` to update
        the GUI status label.

        Parameters
        ----------
        by_user : bool, optional
            If ``True``, the ramp was stopped by the user (via :meth:`stop_ramp`)
            rather than completing normally. This only affects the logged message
            (default ``False``).
        '''
        self.doing_ramp = False
        self.sig_ramp.emit(self.SIG_RAMP_ENDED)
        if by_user:
            self.logger.info(f"Ramp stopped.")
        else:
            self.logger.info(f"Sequence terminated.")
        for action in self.list_functions_ramp_ended:
            action() 
        self.send_ramp_status()
        return
    
    def _run_sequence(self,index):
        '''
        Execute the action at position ``index`` of :attr:`sequence`, then schedule
        the next action.

        If ``index`` is past the end of the sequence, the ramp is considered finished
        and :meth:`ramp_ended` is called. If ``doing_ramp`` is ``False`` (e.g. the
        ramp was stopped by the user), the method returns immediately without executing
        anything further.

        Each action type is handled as follows:

        - ``'move'``: calls ``func_move(stepsize)``, increments ``numb_steps_done``,
          then polls ``func_check_step_has_ended`` via
          :meth:`~abstract_classes.abstract_interface.check_property_until` until the
          step completes, at which point ``_run_sequence(index+1)`` is scheduled.
        - ``'wait'``: schedules ``_run_sequence(index+1)`` after ``action['time']``
          seconds via ``QtCore.QTimer.singleShot``.
        - ``'send_trigger'``: calls ``func_trigger()`` if set, then either waits for
          ``func_trigger_continue_ramp()`` to return ``True`` (if set) or immediately
          proceeds to ``_run_sequence(index+1)``.
        - ``'reset_initial_value'``: calls :meth:`reset_to_initial_value`, then polls
          ``func_check_step_has_ended`` before proceeding.

        Parameters
        ----------
        index : int
            Index of the action to execute in :attr:`sequence`.
        '''
        if index >= len(self.sequence):
            self.ramp_ended()
        if self.doing_ramp == False:
            return
        self.send_ramp_status()
        # Execute current action
        current_action = self.sequence[index]
        if current_action['action'] == 'move':
            self.logger.info(f"Will move by {current_action['stepsize']}. Begin moving...")
            self.func_move(current_action['stepsize'])
            self.numb_steps_done = self.numb_steps_done + 1
            self.send_ramp_status()
            #Start checking periodically the value of self.func_check_step_has_ended. If it's false, we call all functions defined in the list self.list_functions_step_not_ended 
            # If it's true, we call all functions defined in the list self.list_functions_step_has_ended, plus the function self._run_sequence(index+1) in order to keep the ramp going, and we stop checking
            abstract_classes.abstract_interface.check_property_until(self.func_check_step_has_ended,[False,True],[self.list_functions_step_not_ended, self.list_functions_step_has_ended + [lambda: self._run_sequence(index+1)]])
        if current_action['action'] == 'wait':
            self.logger.info(f"Waiting for {float(current_action['time'])} s...")
            QtCore.QTimer.singleShot(int(current_action['time']*1e3), lambda :  self._run_sequence(index+1))
        if current_action['action'] == 'send_trigger':
            if self.func_trigger:
                self.logger.info(f"Calling the trigger function...")
                self.func_trigger() 
                if self.func_trigger_continue_ramp:
                    abstract_classes.abstract_interface.check_property_until(self.func_trigger_continue_ramp,[False,True],[[], [lambda: self._run_sequence(index+1)]])    
                    return
            self._run_sequence(index+1)
        if current_action['action'] == 'reset_initial_value':
            self.reset_to_initial_value()
            abstract_classes.abstract_interface.check_property_until(self.func_check_step_has_ended,[False,True],[[], [lambda: self._run_sequence(index+1)]])
        
    def generate_list_actions(self, initial_trigger, stepsize, wait1, send_trigger, wait2, numb_steps, add_reverse = False, repeat_ramp=1, reset_after_ramp=1):
        '''
        Build the ordered list of actions that fully describes one ramp run.

        Each action is a dict with an ``'action'`` key whose value is one of
        ``'move'``, ``'wait'``, ``'send_trigger'``, or ``'reset_initial_value'``,
        plus any extra parameters needed by that action (``'stepsize'`` for
        ``'move'``, ``'time'`` for ``'wait'``).

        Parameters
        ----------
        initial_trigger : bool
            If ``True``, prepend a ``send_trigger`` action (followed by a ``wait`` of
            ``wait2``) before the ramp starts.
        stepsize : float
            Value used for each forward ``'move'`` action. Negated for reverse steps.
        wait1 : float
            Wait time (in s) inserted after each ``'move'`` action.
        send_trigger : bool
            If ``True``, a ``send_trigger`` action is inserted after each step
            (following ``wait1``), in both the forward and reverse legs.
        wait2 : float
            Wait time (in s) inserted after each (potential) trigger.
        numb_steps : int
            Number of steps in the forward (and reverse, if enabled) sweep.
        add_reverse : bool, optional
            If ``True``, append a mirrored sequence of ``numb_steps`` steps with
            negated ``stepsize`` after the forward sweep (default ``False``).
        repeat_ramp : int, optional
            Number of times the forward (+ optional reverse) sequence is repeated
            (default ``1``).
        reset_after_ramp : bool or int, optional
            If ``True``, append a ``'reset_initial_value'`` action at the very end
            of the sequence (default ``1``).

        Returns
        -------
        list of dict
            The ordered sequence of actions, consumed one at a time by
            :meth:`run_sequence` / :meth:`_run_sequence`.
        '''
        action =[]
        if initial_trigger:
            action.append({'action':'send_trigger'})
            action.append({'action':'wait', 'time':wait2})
        for j in range(repeat_ramp): #when repeat_ramp > 1, the whole ramp is repeated multiple times
            for i in range(numb_steps):
                action.append({'action':'move', 'stepsize':stepsize})
                action.append({'action':'wait', 'time':wait1})
                if send_trigger:
                    action.append({'action':'send_trigger'})
                action.append({'action':'wait', 'time':wait2})
            if add_reverse:
                for i in range(numb_steps):
                    action.append({'action':'move', 'stepsize':-stepsize})
                    action.append({'action':'wait', 'time':wait1})
                    if send_trigger:
                        action.append({'action':'send_trigger'})
                    action.append({'action':'wait', 'time':wait2})
        if reset_after_ramp:
            action.append({'action':'reset_initial_value'})    
        return action
    
    def connect_to_ramp_child(self,child_ramp):#:instrument1,instrument2):
        '''
        Connect this ramp object to the ramp object specified by ``child_ramp``.

        The trigger function of this ramp (``func_trigger``) is temporarily replaced
        by ``child_ramp.start_ramp``, and ``func_trigger_continue_ramp`` is replaced
        by ``child_ramp.is_not_doing_ramp``. This means that every time this ramp
        fires a trigger, it will start a full run of ``child_ramp`` and wait for it
        to finish before continuing.

        The previous values of ``func_trigger`` and ``func_trigger_continue_ramp``
        are saved internally so that they can be restored by
        :meth:`disconnect_from_ramp_child`.

        Parameters
        ----------
        child_ramp : ramp
            The ramp object to connect as a child. Its ``has_parent_ramp`` flag and
            ``parent_ramp`` reference are updated accordingly.
        '''
        self.func_trigger_old = self.func_trigger                               #store old value of func_trigger for later restore
        self.func_trigger_continue_ramp_old = self.func_trigger_continue_ramp   #store old value of func_trigger_continue_ramp for later restore
        self.child_ramp = child_ramp
        self.func_trigger = self.child_ramp.start_ramp
        self.func_trigger_continue_ramp = self.child_ramp.is_not_doing_ramp
        self.has_child_ramp = True
        self.child_ramp.has_parent_ramp = True
        self.child_ramp.parent_ramp = self
        self.send_ramp_status()
        self.child_ramp.send_ramp_status()

    def disconnect_from_ramp_child(self):
        '''
        Disconnect this ramp from its child ramp, restoring the original trigger
        configuration.

        Restores ``func_trigger`` and ``func_trigger_continue_ramp`` to the values
        they had before :meth:`connect_to_ramp_child` was called, clears the child
        ramp's ``has_parent_ramp`` flag and ``parent_ramp`` reference, and calls
        :meth:`send_ramp_status` on this ramp to update the GUI.

        Has no effect if no child ramp is currently connected.
        '''
        if not self.has_child_ramp: return #Suggested by Claude
        self.func_trigger = self.func_trigger_old    
        self.func_trigger_continue_ramp = self.func_trigger_continue_ramp_old 
        self.has_child_ramp = False
        self.child_ramp.has_parent_ramp = False
        self.child_ramp.parent_ramp = None
        self.child_ramp = None
        self.send_ramp_status()
        
class ramp_gui(Qt.QGroupBox,abstract_classes.abstract_gui):
    """
    PyQt5 GUI panel for a :class:`ramp` object.

    Inherits from both ``Qt.QGroupBox`` (so it can be dropped directly into a parent
    layout as a self-contained widget) and
    :class:`~abstract_classes.abstract_gui` (to access the :meth:`~abstract_classes.abstract_gui.disable_widget`
    and :meth:`~abstract_classes.abstract_gui.enable_widget` helpers).

    The panel exposes all ramp settings (step size, wait times, number of steps,
    repeat count, reverse/reset/initial-trigger checkboxes) and a single "Start Ramp"
    / "Stop Ramp" toggle button. A status label shows the current ramp progress and
    any parent/child ramp connection.
    """
    def __init__(self,ramp_object):
        '''
        Parameters
        ----------
        ramp_object : ramp
            The ramp model object that this GUI controls. Stored as ``self.ramp``.
        '''
        super().__init__()
        self.ramp = ramp_object
        self.initialize()
       
    def initialize(self):
        '''
        Build the GUI, wire up all widget events to their handler methods, connect
        model signals to event slots, and set the initial widget state.

        Called automatically by :meth:`__init__`. Specifically:

        1. Calls :meth:`create_widgets` to instantiate all Qt widgets.
        2. Connects widget events (button clicks, text edits, checkbox toggles,
           spinbox changes) to the corresponding handler methods.
        3. Connects signals emitted by :attr:`ramp` and its ``interface`` to the
           event slot methods of this GUI.
        4. Calls ``ramp.send_settings()`` to push current settings to the GUI, and
           sets the initial disabled/enabled state to match the current connection
           status (starting in the disconnected state).
        '''
        self.create_widgets()
        ### Connect widgets events to functions
        self.button_StartRamp.clicked.connect(self.click_button_start_ramp)
        self.edit_StepSize.returnPressed.connect(self.press_enter_edit_StepSize)
        self.edit_StepSize.editingFinished.connect(self.press_enter_edit_StepSize)
        self.edit_Wait1.returnPressed.connect(self.press_enter_edit_Wait1)
        self.edit_Wait1.editingFinished.connect(self.press_enter_edit_Wait1)
        self.edit_Wait2.returnPressed.connect(self.press_enter_edit_Wait2)
        self.edit_Wait2.editingFinished.connect(self.press_enter_edit_Wait2)
        self.spinbox_steps.valueChanged.connect(self.value_changed_spinbox_steps)
        self.spinbox_repeat.valueChanged.connect(self.value_changed_spinbox_repeat)
        self.checkbox_Reverse.stateChanged.connect(self.click_box_Reverse)
        self.checkbox_Reset.stateChanged.connect(self.click_box_Reset)
        self.checkbox_Initial_trigger.stateChanged.connect(self.click_box_Initial_trigger)
        
        ### Connect signals from model to event slots of this GUI
        self.ramp.sig_ramp.connect(self.on_ramp_state_changed)
        self.ramp.sig_ramp_settings.connect(self.on_settings_changed)
        self.ramp.sig_ramp_info.connect(self.on_ramp_info_received)
        self.ramp.interface.sig_change_moving_status.connect(self.on_moving_state_change)
        self.ramp.interface.sig_connected.connect(self.on_connection_status_change)
        
        
        ### SET INITIAL STATE OF WIDGETS
        self.ramp.send_settings()
        self.on_connection_status_change(self.ramp.interface.SIG_DISCONNECTED) 

    def create_widgets(self):
        '''
        Instantiate and lay out all Qt widgets that make up the ramp panel.

        Builds two horizontal rows inside a ``QVBoxLayout`` set as the group box
        layout:

        - Row 1: initial-trigger checkbox, step size edit, wait-1 edit,
          wait-2 edit, number-of-steps spinbox.
        - Row 2: reverse checkbox, repeat spinbox, reset checkbox,
          "Start / Stop Ramp" button, and a status label.

        All widgets are stored as instance attributes and also collected into
        ``self.list_widgets`` for use with :meth:`~abstract_classes.abstract_gui.enable_widget`
        and :meth:`~abstract_classes.abstract_gui.disable_widget`.
        '''
        self.setTitle(f"Ramp (id = {self.ramp.id})")
        ramp_vbox = Qt.QVBoxLayout()
        ramp_hbox1 = Qt.QHBoxLayout()
        ramp_hbox2 = Qt.QHBoxLayout()
        self.checkbox_Initial_trigger = Qt.QCheckBox("Send initial trigger (+wait)")
        tooltip = 'When this interface is used within a larger software, it can be set to send a trigger (to another function) everytime a step of the ramp is done (see documentation).\nBy ticking this on, a trigger is sent also at the beginning of the ramp.'
        self.checkbox_Initial_trigger.setToolTip(tooltip)
        self.label_Move = Qt.QLabel("Move by")
        self.edit_StepSize = Qt.QLineEdit()
        self.label_Wait1 = Qt.QLabel(",wait for")
        self.edit_Wait1 = Qt.QLineEdit()
        self.edit_Wait1.setMaximumWidth(35)
        self.label_Wait2 = Qt.QLabel("s, send trigger, wait for")
        self.edit_Wait2 = Qt.QLineEdit()
        self.edit_Wait2.setMaximumWidth(35)
        self.label_steps = Qt.QLabel("s, repeat")
        self.spinbox_steps = Qt.QSpinBox()
        self.spinbox_steps.setRange(1, 100000)
        self.label_steps2 = Qt.QLabel("times.")
        self.widgets_row1 = [self.checkbox_Initial_trigger, self.label_Move, self.edit_StepSize, self.label_Wait1,
                                        self.edit_Wait1, self.label_Wait2, self.edit_Wait2,self.label_steps, self.spinbox_steps, self.label_steps2]
        for w in self.widgets_row1:
            ramp_hbox1.addWidget(w)
        ramp_hbox1.addStretch(1) 

        self.checkbox_Reverse = Qt.QCheckBox("and reverse.")
        self.label_repeat = Qt.QLabel(" Repeat ramp")
        self.spinbox_repeat = Qt.QSpinBox()
        self.spinbox_repeat.setRange(1, 100000)
        self.label_repeat2 = Qt.QLabel(" times.")
        self.checkbox_Reset = Qt.QCheckBox("Reset value at the end.")
        self.checkbox_Reset.setToolTip('When the ramp is done, resets the value of the controlled parameter to the initial one.')
        self.button_StartRamp = Qt.QPushButton("Start Ramp")
        self.label_StatusRamp = Qt.QLabel("")
        self.widgets_row2 = [self.checkbox_Reverse, self.label_repeat, self.spinbox_repeat ,
                                        self.label_repeat2, self.checkbox_Reset, self.button_StartRamp]
        for w in self.widgets_row2:
            ramp_hbox2.addWidget(w)
        ramp_hbox2.addWidget(self.label_StatusRamp)
        ramp_hbox2.addStretch(1) 

        ramp_vbox.addLayout(ramp_hbox1)  
        ramp_vbox.addLayout(ramp_hbox2)  
        self.setLayout(ramp_vbox ) 
        self.list_widgets = self.widgets_row1 + self.widgets_row2

        # Widgets for which we want to constraint the width by using sizeHint()
        widget_list = self.widgets_row1 + self.widgets_row2[:-1]
        for w in widget_list:
            w.setMaximumSize(w.sizeHint())


###########################################################################################################
### Event Slots. They are normally triggered by signals from the model, and change the GUI accordingly  ###
###########################################################################################################

    def on_ramp_state_changed(self,status):
        '''
        Event slot connected to :attr:`ramp.sig_ramp`.

        Switches the GUI between the "doing ramp" and "not doing ramp" visual state
        depending on whether ``status`` is :attr:`~ramp.SIG_RAMP_STARTED` or
        :attr:`~ramp.SIG_RAMP_ENDED`.

        Parameters
        ----------
        status : int
            One of the ``SIG_RAMP_*`` codes emitted by :attr:`ramp.sig_ramp`.
        '''
        if status == self.ramp.SIG_RAMP_STARTED:
            self.set_doingramp_state()
        if status == self.ramp.SIG_RAMP_ENDED:
            self.set_notdoingramp_state()
            
    def on_settings_changed(self,settings):
        '''
        Event slot connected to :attr:`ramp.sig_ramp_settings`.

        Updates all editable widgets to reflect the values in ``settings``. Called
        both when a setting changes and when the model explicitly pushes its current
        state (e.g. to revert a widget after an invalid input).

        Parameters
        ----------
        settings : dict
            The current :attr:`ramp.settings` dictionary.
        '''
        self.checkbox_Initial_trigger.setChecked(bool(settings['ramp_send_initial_trigger']))
        self.edit_StepSize.setText(str(settings['ramp_step_size']))
        self.edit_Wait1.setText(str(settings['ramp_wait_1']))
        self.edit_Wait2.setText(str(settings['ramp_wait_2']))
        self.spinbox_steps.setValue(int(settings[ 'ramp_numb_steps']))
        self.checkbox_Reverse.setChecked(bool(settings['ramp_reverse']))
        self.checkbox_Reset.setChecked(bool(settings['ramp_reset']))
        self.spinbox_repeat.setValue(int(settings[ 'ramp_repeat']))

    def on_connection_status_change(self,status):
        '''
        Event slot connected to ``ramp.interface.sig_connected``.

        Disables all ramp widgets while the instrument is disconnected, disconnecting,
        or connecting; enables them when the instrument is fully connected.

        Parameters
        ----------
        status : int
            One of the ``SIG_CONNECTED/DISCONNECTED/CONNECTING/DISCONNECTING`` codes
            emitted by ``ramp.interface.sig_connected``.
        '''
        if status in [self.ramp.interface.SIG_DISCONNECTED,self.ramp.interface.SIG_DISCONNECTING,self.ramp.interface.SIG_CONNECTING]:
            self.disable_widget(self.list_widgets)
        if status == self.ramp.interface.SIG_CONNECTED:
            self.enable_widget(self.list_widgets)

    def on_moving_state_change(self,status):
        '''
        Event slot connected to ``ramp.interface.sig_change_moving_status``.

        Disables all ramp widgets while the instrument is moving; re-enables them
        when the movement has ended, but only if no ramp is currently in progress.

        Parameters
        ----------
        status : int
            One of ``SIG_MOVEMENT_STARTED`` or ``SIG_MOVEMENT_ENDED`` as emitted by
            ``ramp.interface.sig_change_moving_status``.
        '''
        if status == self.ramp.interface.SIG_MOVEMENT_STARTED:
            self.disable_widget(self.list_widgets)
        if status == self.ramp.interface.SIG_MOVEMENT_ENDED and self.ramp.is_not_doing_ramp():
            self.enable_widget(self.list_widgets)

    def on_ramp_info_received(self,list_info):
        '''
        Event slot connected to :attr:`ramp.sig_ramp_info`.

        Updates the status label with the current ramp state and connection info.
        If ``list_info[1]`` (the connection info string) is non-empty, both strings
        are shown on separate lines; otherwise only ``list_info[0]`` is shown.

        Parameters
        ----------
        list_info : list of str
            A two-element list ``[ramp_status_string, connection_info_string]`` as
            emitted by :meth:`ramp.send_ramp_status`.
        '''
        if not(list_info[1] == ''):
            self.label_StatusRamp.setText(f"{str(list_info[0])}<br/>{str(list_info[1])}")
        else:
            self.label_StatusRamp.setText(str(list_info[0]))
    
#######################
### END Event Slots ###
#######################

    def click_button_start_ramp(self):
        '''
        Handler for the "Start Ramp" / "Stop Ramp" button.

        If no ramp is currently running, reads the current widget values into a
        settings dict, applies them via :meth:`ramp.set_ramp_settings`, and calls
        :meth:`ramp.start_ramp`. If a ramp is already running, calls
        :meth:`ramp.stop_ramp` instead.
        '''
        if self.ramp.doing_ramp == False:

            settings = {   
                    'ramp_step_size': float(self.edit_StepSize.text()),
                    'ramp_wait_1': float(self.edit_Wait1.text()),
                    'ramp_wait_2': float(self.edit_Wait2.text()),
                    'ramp_numb_steps': int(self.spinbox_steps.value()),
                    'ramp_repeat': int(self.spinbox_repeat.value()),
                    'ramp_reverse': self.checkbox_Reverse.isChecked(),
                    'ramp_send_initial_trigger': (self.checkbox_Initial_trigger.isChecked() == True),
                    'ramp_reset' : (self.checkbox_Reset.isChecked() == True)
                     }

            self.ramp.set_ramp_settings(settings)
            self.ramp.start_ramp()
        else:
            self.ramp.stop_ramp()
            
    def press_enter_edit_StepSize(self):
        '''Handler for the step size line edit (Return pressed or editing finished).
        Reads the current text and forwards it to :meth:`ramp.set_setting`.'''
        StepSize = self.edit_StepSize.text()
        self.ramp.set_setting('ramp_step_size', StepSize)
    
    def press_enter_edit_Wait1(self):
        '''Handler for the wait-1 line edit (Return pressed or editing finished).
        Reads the current text and forwards it to :meth:`ramp.set_setting`.'''
        WaitTime = self.edit_Wait1.text()
        self.ramp.set_setting('ramp_wait_1', WaitTime)
    
    def press_enter_edit_Wait2(self):
        '''Handler for the wait-2 line edit (Return pressed or editing finished).
        Reads the current text and forwards it to :meth:`ramp.set_setting`.'''
        WaitTime = self.edit_Wait2.text()
        self.ramp.set_setting('ramp_wait_2', WaitTime)
        
    def click_box_Initial_trigger(self,state):
        '''Handler for the "Send initial trigger" checkbox. Converts the Qt check
        state to bool and forwards it to :meth:`ramp.set_setting`.'''
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_send_initial_trigger',state_bool)
        
    def click_box_Reverse(self,state):
        '''Handler for the "and reverse" checkbox. Converts the Qt check state to
        bool and forwards it to :meth:`ramp.set_setting`.'''
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_reverse',state_bool)
    
    def click_box_Reset(self,state):
        '''Handler for the "Reset value at the end" checkbox. Converts the Qt check
        state to bool and forwards it to :meth:`ramp.set_setting`.'''
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_reset',state_bool)
        
    def value_changed_spinbox_steps(self):
        '''Handler for the number-of-steps spinbox. Forwards the current value to
        :meth:`ramp.set_setting`.'''
        self.ramp.set_setting('ramp_numb_steps',self.spinbox_steps.value())
        
    def value_changed_spinbox_repeat(self):
        '''Handler for the repeat-count spinbox. Forwards the current value to
        :meth:`ramp.set_setting`.'''
        self.ramp.set_setting('ramp_repeat',self.spinbox_repeat.value())
        
    def set_doingramp_state(self, text = "Stop Ramp"):
        '''
        Switch the GUI into the "ramp in progress" visual state.

        Disables all ramp widgets except the start/stop button (so the user can still
        stop the ramp), and changes the button label to "Stop Ramp".
        '''
        self.disable_widget(self.list_widgets)
        self.enable_widget([self.button_StartRamp])
        self.button_StartRamp.setText("Stop Ramp")
            
    def set_notdoingramp_state(self, text = "Start Ramp"):
        '''
        Switch the GUI into the "no ramp running" visual state.

        Re-enables all ramp widgets and changes the start/stop button label back to
        "Start Ramp".
        '''
        self.enable_widget(self.list_widgets)
        self.button_StartRamp.setText("Start Ramp")