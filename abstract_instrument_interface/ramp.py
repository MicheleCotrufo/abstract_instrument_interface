from typing_extensions import Self
from xml.dom.expatbuilder import parseFragmentString
from abstract_instrument_interface import abstract_classes
import PyQt5.QtCore as QtCore
import PyQt5.QtWidgets as Qt# QApplication, QWidget, QMainWindow, QPushButton, QHBoxLayout
import PyQt5.QtGui as QtGui
import logging

class ramp(QtCore.QObject):
    """
    Many instruments require having a ramp panel in their GUI, which allows to sweep a certain parameter and send a trigger. This class generates a general "ramp panel", which can then be customized 
    by the child instance, and it contains the minimal logic to do a ramp.
    It inherits from abstract_interface, in order to use some of its methods

    Important: the interface object that istantiate this ramp() object needs to have some QtCore.pyqtSignal objects defined as attributes, in order to communicate with this ramp() object
    
    ## SIGNALS that need to be defined as attributes of self.interface, together with their flags

                                                               | Triggered when ...                               | Send as parameter    
                                                                ------------------------------------------------------------------------------------------------
    sig_connected = QtCore.pyqtSignal(int)                     | The connection stateus of interface changed      | self.interface.SIG_CONNECTED, self.interface.SIG_DISCONNECTED, self.interface.SIG_CONNECTING, self.interface.SIG_DISCONNECTING
    sig_change_moving_status = QtCore.pyqtSignal(int)          | The movement status of interface changed         | self.interface.SIG_MOVEMENT_STARTED, self.interface.SIG_MOVEMENT_ENDED
    
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
    sig_ramp = QtCore.pyqtSignal(int)                       #   | Ramp event                                                                        | 
    sig_ramp_settings = QtCore.pyqtSignal(dict)             #   | One of the settings changed, or when the GUI requested it                         |
    sig_ramp_info = QtCore.pyqtSignal(list)                 #   | General info released by the model, typically used in a status label in the GUI   |

    def __init__(self, interface):
        '''
        'ramp_send_initial_trigger'
            bool
        'ramp_step_size'
            float
        'ramp_wait_1'
            float
        'ramp_send_trigger' 
            bool
        'ramp_wait_2' 
            float
        'ramp_numb_steps'
            int, positive
        'ramp_reverse'
            bool
        'ramp_repeat'
            int, positive
        'ramp_reset'
            bool
        '''
        #super().__init__(app=interface.app)
        super().__init__()
        self.interface = interface          #Interface object which is using this ramp object
        self.logger = self.interface.logger
        self.doing_ramp = False             #Flag variable used to keep track of when a ramp is being done
        self.settings = {                   ### Default values of settings (might be overlapped by settings saved in .json files later)
            'ramp_step_size': 1,            #Increment value of each ramp step
            'ramp_wait_1': 1,               #Wait time (in s) after each ramp step
            'ramp_send_trigger' : True,     #If true, the function self.func_trigger is called after each 'movement'
            'ramp_wait_2': 1,               #Wait time (in s) after each (potential) call to trigger, before doing the new ramp step
            'ramp_numb_steps': 10,          #Number of steps in the ramp
            'ramp_repeat': 1,               #How many times the ramp is repeated
            'ramp_reverse': 1,              #If True (or 1), it repeates the ramp in reverse
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
                                    list_functions_step_not_ended=[],  
                                    list_functions_step_has_ended=[],  
                                    list_functions_ramp_ended =[]):
        '''
        func_move
            function, takes a single parameter as input
        func_check_step_has_ended
            function, takes no parameter in input, returns true when the step has ended, false othwerwise
        func_trigger
            function, takes no parameter as input
        func_trigger_continue_ramp
            function, takes no parameter as input. It can be set to None.
            If different from None, after the function func_trigger is invoked, the ramp will wait until
            func_trigger_continue_ramp() == True before doing the next ramp steps. (Note: this waiting time adds up to the wime set by wait1 and wait2)
        func_set_value
            function, no input parameter. Sets the instrument connected to this ramp object to a given value
        func_read_current_value
            function, takes no input parameter. Read the current value of the instrument connected to this ramp object
        list_functions_step_not_ended
            list, contains functions that takes no parameter in input. 
            When doing a ramp, after each step is executed, we check wheter the step has ended or not. Everytime that the step has not ended, all functions in this list are executed
        list_functions_step_has_ended
            list, contains functions that takes no parameter in input. 
            When doing a ramp, after each step is executed, we check wheter the step has ended or not. When the step has ended, all functions in this list are executed   
        list_functions_ramp_ended 
            list, contains functions that takes no parameter in input. 
            When the ramp is over all these functions are executed
        '''
        self.func_move = func_move
        self.func_trigger = func_trigger
        self.func_trigger_continue_ramp = func_trigger_continue_ramp
        self.func_set_value = func_set_value      # This and next function are useful for resetting the instrument back to its original position. They can be set to none.
        self.func_read_current_value = func_read_current_value  
        self.func_check_step_has_ended = func_check_step_has_ended
        self.list_functions_step_not_ended = list_functions_step_not_ended
        self.list_functions_step_has_ended = list_functions_step_has_ended
        self.list_functions_ramp_ended = list_functions_ramp_ended

    def set_ramp_settings(self,settings):
        self.settings.update(settings)
    
    def set_setting(self,setting_name,setting_value,log=True):
        #Settings are grouped by (1) their type and (2) the range of values they can have
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
            try: 
                setting_value = bool(setting_value)
                flag_succesful = True
            except ValueError:
                self.logger.error(f"{setting_name} must be a boolean(-like) variable.")
                flag_emit_current_settings = True
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
        self.doing_ramp = True
        self.run_sequence(actions)
        
    def reset_to_initial_value(self):
        if self.func_set_value and hasattr(self,'initial_value'):
            try:
                self.logger.info(f"Resetting ramp parameter to original value = {self.initial_value}...")
                self.func_set_value(self.initial_value)    
            except:
                pass
        return
    
    def is_doing_ramp(self):
        return self.doing_ramp

    def is_not_doing_ramp(self):
        return not(self.is_doing_ramp())
    
    def stop_ramp(self):
        if self.doing_ramp == True:
            self.ramp_ended(by_user = True)
        
    def run_sequence(self,sequence):
        self.sequence = sequence
        self._run_sequence(0)
        
    def ramp_ended(self,by_user = False):
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
        #generate a list of actions that define a ramp
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
                    action.append({'action':'send_trigger'})
                    action.append({'action':'wait', 'time':wait2})
        if reset_after_ramp:
            action.append({'action':'reset_initial_value'})    
        return action
    
    def connect_to_ramp_child(self,child_ramp):#:instrument1,instrument2):
        '''
        Connect this ramp object to the ramp object specified by child_ramp. 
        Specifically, the trigger function of this ramp object is set equal to the start_ramp method of child_ramp, and 
        the func_trigger_continue_ramp function of this ramp object is set equal to the method is_not_doing_ramp of child_ramp
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
        self.func_trigger = self.func_trigger_old    
        self.func_trigger_continue_ramp = self.func_trigger_continue_ramp_old 
        self.has_child_ramp = False
        self.child_ramp.has_parent_ramp = False
        self.child_ramp.parent_ramp = None
        self.child_ramp = None
        self.send_ramp_status()
        
class ramp_gui(Qt.QGroupBox,abstract_classes.abstract_gui):
    """
    It inherits from abstract_gui, mainly to be able to access general purpose functions such as disable_widget and enable_widget. Might change this in the future
    """
    def __init__(self,ramp_object):
        super().__init__()
        self.ramp = ramp_object
        self.initialize()
       
    def initialize(self):
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
        if status == self.ramp.SIG_RAMP_STARTED:
            self.set_doingramp_state()
        if status == self.ramp.SIG_RAMP_ENDED:
            self.set_notdoingramp_state()
            
    def on_settings_changed(self,settings):
        self.checkbox_Initial_trigger.setChecked(bool(settings['ramp_send_initial_trigger']))
        self.edit_StepSize.setText(str(settings['ramp_step_size']))
        self.edit_Wait1.setText(str(settings['ramp_wait_1']))
        self.edit_Wait2.setText(str(settings['ramp_wait_2']))
        self.spinbox_steps.setValue(int(settings[ 'ramp_numb_steps']))
        self.checkbox_Reverse.setChecked(bool(settings['ramp_reverse']))
        self.checkbox_Reset.setChecked(bool(settings['ramp_reset']))
        self.spinbox_repeat.setValue(int(settings[ 'ramp_repeat']))

    def on_connection_status_change(self,status):
        if status in [self.ramp.interface.SIG_DISCONNECTED,self.ramp.interface.SIG_DISCONNECTING,self.ramp.interface.SIG_CONNECTING]:
            self.disable_widget(self.list_widgets)
        if status == self.ramp.interface.SIG_CONNECTED:
            self.enable_widget(self.list_widgets)

    def on_moving_state_change(self,status):
        if status == self.ramp.interface.SIG_MOVEMENT_STARTED:
            self.disable_widget(self.list_widgets)
        if status == self.ramp.interface.SIG_MOVEMENT_ENDED and self.ramp.is_not_doing_ramp():
            self.enable_widget(self.list_widgets)

    def on_ramp_info_received(self,list_info):
        if not(list_info[1] == ''):
            self.label_StatusRamp.setText(f"{str(list_info[0])}<br/>{str(list_info[1])}")
        else:
            self.label_StatusRamp.setText(str(list_info[0]))
    
#######################
### END Event Slots ###
#######################

    def click_button_start_ramp(self):
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
        StepSize = self.edit_StepSize.text()
        self.ramp.set_setting('ramp_step_size', StepSize)
    
    def press_enter_edit_Wait1(self):
        WaitTime = self.edit_Wait1.text()
        self.ramp.set_setting('ramp_wait_1', WaitTime)
    
    def press_enter_edit_Wait2(self):
        WaitTime = self.edit_Wait2.text()
        self.ramp.set_setting('ramp_wait_2', WaitTime)
        
    def click_box_Initial_trigger(self,state):
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_send_initial_trigger',state_bool)
        
    def click_box_Reverse(self,state):
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_reverse',state_bool)
    
    def click_box_Reset(self,state):
        state_bool = (state == QtCore.Qt.Checked)
        self.ramp.set_setting('ramp_reset',state_bool)
        
    def value_changed_spinbox_steps(self):
        self.ramp.set_setting('ramp_numb_steps',self.spinbox_steps.value())
        
    def value_changed_spinbox_repeat(self):
        self.ramp.set_setting('ramp_repeat',self.spinbox_repeat.value())
        
    def set_doingramp_state(self, text = "Stop Ramp"):
        self.disable_widget(self.list_widgets)
        self.enable_widget([self.button_StartRamp])
        self.button_StartRamp.setText("Stop Ramp")
            
    def set_notdoingramp_state(self, text = "Start Ramp"):
        self.enable_widget(self.list_widgets)
        self.button_StartRamp.setText("Start Ramp")

