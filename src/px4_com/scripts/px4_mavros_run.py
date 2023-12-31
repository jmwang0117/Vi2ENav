#!/usr/bin/env python
import rospy
from mavros_msgs.msg import GlobalPositionTarget, State, PositionTarget
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from geometry_msgs.msg import PoseStamped, Twist
from sensor_msgs.msg import Imu, NavSatFix
from std_msgs.msg import Float32, Float64, String
import time
from pyquaternion import Quaternion
import math
import threading

class Px4Controller:
    def __init__(self):
        self.imu = None
        self.gps = None
        self.local_pose = None
        self.current_state = None
        self.current_heading = None
        self.takeoff_height = 0.5
        self.local_enu_position = None
        self.local_pose = None
        self.cur_target_pose = None
        self.globale_target = None
        self.received_new_task = False
        self.arm_state = False
        self.offboard_state = False
        self.takeoff_state = False
        self.received_imu = False
        self.frame = "BODY"
        self.state = None
        self.mavros_state = None

        self.local_pose_sub = rospy.Subscriber("/mavros/local_position/pose", PoseStamped,self.local_pose_callback)
        self.mavros_sub = rospy.Subscriber("/mavros/state", State, self.mavros_state_callback)
        self.gps_sub = rospy.Subscriber("/mavros/global_position/global", NavSatFix, self.gps_callback)
        self.imu_sub = rospy.Subscriber("/mavros/imu/data", Imu, self.imu_callback)
        self.move_sub = rospy.Subscriber("/set_pose/position", PoseStamped, self.set_target_position_callback) 
        self.custom_activity_sub = rospy.Subscriber("/gesture/command", String, self.custom_activity_callback)

        self.local_target_pub = rospy.Publisher("/mavros/setpoint_raw/local", PositionTarget, queue_size=10)
        self.armService = rospy.ServiceProxy("/mavros/cmd/arming", CommandBool)
        self.flightModeService = rospy.ServiceProxy("/mavros/set_mode", SetMode)

        print("Px4 Controller Initialized!!")
    
    def start(self):
        rospy.init_node("px4_mavros_run")
        time.sleep(1)
        '''
        current_pose_x = self.local_pose.pose.position.x
        current_pose_y = self.local_pose.pose.position.y
        print("current_pose_x: " + str(current_pose_x) + " current_pose_y: " + str(current_pose_y) + "  current_heading: " + str(self.current_heading))
        '''
        self.cur_target_pose = self.construct_target(0.0, 0.0, 0.0, 0.0)
        time.sleep(2)
        ######main ROS thread#####
        while (rospy.is_shutdown() is False):
            self.local_target_pub.publish(self.cur_target_pose)
            self.print_info()
            time.sleep(0.1)
        
    def construct_target(self, x, y, z, yaw, yaw_rate = 1):
        target_raw_pose = PositionTarget()
        target_raw_pose.header.stamp = rospy.Time.now()
        target_raw_pose.coordinate_frame = 9
        target_raw_pose.position.x = x
        target_raw_pose.position.y = y
        target_raw_pose.position.z = z
        target_raw_pose.type_mask = PositionTarget.IGNORE_VX + PositionTarget.IGNORE_VY + PositionTarget.IGNORE_VZ + PositionTarget.IGNORE_AFX + PositionTarget.IGNORE_AFY + PositionTarget.IGNORE_AFZ  + PositionTarget.FORCE
        target_raw_pose.yaw = yaw
        target_raw_pose.yaw_rate = yaw_rate
        return target_raw_pose
    
    def position_distance(self, cur_p, target_p, threshold=0.1):
        delta_x = math.fabs(cur_p.pose.position.x - target_p.position.x)
        delta_y = math.fabs(cur_p.pose.position.y - target_p.position.y)
        delta_z = math.fabs(cur_p.pose.position.z - target_p.position.z)
        if (delta_x + delta_y + delta_z < threshold):
            return True
        else:
            return False
    
    def local_pose_callback(self, msg):
        self.local_pose = msg
        self.local_enu_position = msg
    
    def mavros_state_callback(self, msg):
        self.state = msg
        self.offboard_state = self.state.guided
        self.arm_state = self.state.armed
    
    def imu_callback(self, msg):
        global global_imu, current_heading
        self.imu = msg
        self.current_heading = self.q2yaw(self.imu.orientation)
        self.received_imu = True
    
    def gps_callback(self, msg):
        self.gps = msg
    
    def body2enu(self, body_target_x, body_target_y, body_target_Z):
        ENU_x = body_target_y
        ENU_y = -body_target_x
        ENU_z = body_target_Z
        return ENU_x, ENU_y, ENU_z
    
    def BodyOffsetENU2FLU(self, msg):
        FLU_x = msg.pose.position.x * math.cos(self.current_heading) - msg.pose.position.y * math.sin(self.current_heading)
        FLU_y = msg.pose.position.x * math.sin(self.current_heading) + msg.pose.position.y * math.cos(self.current_heading)
        FLU_z = msg.pose.position.z
        return FLU_x, FLU_y, FLU_z
    
    def set_target_position_callback(self, msg):
        rospy.loginfo("Received New Position Task!")
        if msg.header.frame_id == 'base_link':
            self.frame = "BODY"
            rospy.loginfo("Body FLU frame")
            FLU_x, FLU_y, FLU_z = self.BodyOffsetENU2FLU(msg)
            body_x = FLU_x + self.local_pose.pose.position.x
            body_y = FLU_y + self.local_pose.pose.position.y
            body_z = FLU_z + self.local_pose.pose.position.z
            self.cur_target_pose = self.construct_target(body_x, body_y, body_z, self.current_heading)
        else:
            self.frame = "LOCAL_ENU"
            rospy.loginfo("local ENU frame")
            ENU_x, ENU_y, ENU_z = self.body2enu(msg.pose.position.x, msg.pose.position.y, msg.pose.position.z)
            self.cur_target_pose = self.construct_target(ENU_x, ENU_y, ENU_z, self.current_heading)
    
    def custom_activity_callback(self, msg):
        rospy.loginfo("Received Custom Activity")

        if msg.data == "Arm":
            rospy.logwarn("Arming")
            self.arm_state = self.arm()

        elif msg.data == "Disarm":
            rospy.logwarn("Disarming")
            self.arm_state = self.disarm()
        
        elif msg.data == "Offboard":
            rospy.logwarn("Enter offboard")
            self.offboard_state = self.offboard()

        elif msg.data == "Hover":
            rospy.logwarn("HOVERING")
            self.state = "HOVER"
            self.hover()
        
        elif msg.data == "Takeoff":
            rospy.logwarn("Taking OFF")
            self.takeoff()

        elif msg.data == "Land":
            rospy.logwarn("Landing")
            self.land()
        
        elif msg.data == "Forward":
            rospy.logwarn("Moving forward")
            self.move_forward()
        
        elif msg.data == "Backward":
            rospy.logwarn("Moving backward")
            self.move_backward()
        
        elif msg.data == "Left":
            rospy.logwarn("Moving left")
            self.move_left()
        
        elif msg.data == "Right":
            rospy.logwarn("Moving right")
            self.move_right()
        
        elif msg.data == "Up":
            rospy.logwarn("Moving up")
            self.move_up()
        
        elif msg.data == "Down":
            rospy.logwarn("Moving down")
            self.move_down()

        else:
            rospy.logerr("Received Custom Activity not supported yet!")
    
    def set_target_yaw_callback(self, msg):
        rospy.loginfo("Received New Yaw Task!")
        yaw_deg = msg.data * math.pi / 180.0
        self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                     self.local_pose.pose.position.y,
                                                     self.local_pose.pose.position.z,
                                                     yaw_deg)

    def q2yaw(self, q):
        if isinstance(q, Quaternion):
            rotate_z_rad = q.yaw_pitch_roll[0]
        else:
            q_ = Quaternion(q.w, q.x, q.y, q.z)
            rotate_z_rad = q_.yaw_pitch_roll[0]
        return rotate_z_rad 
    
    def takeoff_detection(self):
        if self.local_pose.pose.position.z > 0.3 and self.offboard_state and self.arm_state:
            return True
        else:
            return False 

    ###########command function list############## 
    '''
    1-----arm the uav
    '''
    def arm(self):
        if self.armService(True):
            return True
        else:
            print("Vehicle arming failed!")
            return False
    '''
    2-----disarm the uav
    '''
    def disarm(self):
        if self.armService(False):
            return True
        else:
            print("Vehicle disarming failed!")
            return False
    '''
    3-----enter offboard 
    '''
    def offboard(self):
        if self.flightModeService(custom_mode='OFFBOARD'):
            return True
        else:
            print("Vechile Offboard failed")
            return False
    '''
    4-----hover
    '''
    def hover(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y,
                                                         self.local_pose.pose.position.z,
                                                         self.current_heading)
    '''
    5-----take off
    '''
    def takeoff(self):
        if self.arm_state and self.offboard_state:
            if self.takeoff_detection():
                rospy.logwarn("Vehicle already Took Off!!!!")
            else:
                self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                             self.local_pose.pose.position.y,
                                                             self.takeoff_height,
                                                             self.current_heading) 
    '''
    6-----land
    '''
    def land(self):
        if self.arm_state and self.offboard_state:
            self.state = "LAND"
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y,
                                                         0.1,
                                                         self.current_heading)
    '''
    7-----forward
    '''
    def move_forward(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x + 1.0,
                                                         self.local_pose.pose.position.y,
                                                         self.local_pose.pose.position.z,
                                                         self.current_heading)
    '''
    8-----backward
    '''
    def move_backward(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x - 1.0,
                                                         self.local_pose.pose.position.y,
                                                         self.local_pose.pose.position.z,
                                                         self.current_heading)  
    '''
    9-----left
    '''
    def move_left(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y + 0.6,
                                                         self.local_pose.pose.position.z,
                                                         self.current_heading)  
    '''
    10-----right
    '''
    def move_right(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y - 0.6,
                                                         self.local_pose.pose.position.z,
                                                         self.current_heading) 
    '''
    11-----up
    '''
    def move_up(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y,
                                                         self.local_pose.pose.position.z + 0.3,
                                                         self.current_heading)  
    '''
    12-----down
    '''
    def move_down(self):
        self.takeoff_state = self.takeoff_detection()
        if self.arm_state and self.offboard_state and self.takeoff_state:
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y,
                                                         self.local_pose.pose.position.z - 0.3,
                                                         self.current_heading) 
    def print_info(self):
		rospy.loginfo("################")
		rospy.loginfo("arm_state: " + str(self.arm_state) + "  offboard_state: " + str(self.offboard_state) + "  takeoff_state: " + str(self.takeoff_state)) 
		rospy.loginfo("################")

if __name__ == '__main__':
    con = Px4Controller()
    con.start()                     







