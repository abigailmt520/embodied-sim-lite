import math
import json
import asyncio
import random
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Embodied-SimLite | 具身智能数字孪生：SLAM建图与动态Nav2联合评测基准</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/litegraph.js/css/litegraph.css">
    <style>
        body, html { margin: 0; padding: 0; width: 100vw; height: 100vh; overflow: hidden; background-color: #1a1a1a; font-family: sans-serif; color: white; }
        #main-container { display: flex; width: 100vw; height: 100vh; flex-direction: row; }
        #left-panel { flex: 0 0 36%; height: 100%; border-right: 1px solid #333; background-color: #222; position: relative; min-width: 200px; }
        #resizer { width: 6px; cursor: ew-resize; background-color: #333; transition: background 0.2s; z-index: 100; }
        #resizer:hover { background-color: #00ffcc; }
        #right-panel { flex: 1; height: 100%; background-color: #111; position: relative; overflow: hidden; min-width: 200px; }
        canvas { display: block; outline: none; }
        
        .panel-title { 
            position: absolute; top: 10px; left: 20px; 
            color: #00ffcc; font-family: monospace; 
            z-index: 1000; pointer-events: none; 
            text-shadow: 1px 1px 2px black;
            background: rgba(0,0,0,0.6); 
            padding: 8px 12px; border-radius: 6px;
        }
        .app-brand { display: block; font-size: 1.2em; font-weight: bold; color: #fff; margin-bottom: 4px; }
        
        #telemetry { position: absolute; top: 20px; right: 20px; background: rgba(0,0,0,0.8); padding: 15px; border-radius: 8px; font-family: monospace; border: 1px solid #444; z-index: 1000; pointer-events: none; min-width: 220px;}
        .tel-row { display: flex; justify-content: space-between; margin: 5px 0; font-size: 13px; }
        .truth { color: #00ffcc; }
        .odom { color: #ff4444; }
        #canvas-container { width: 100%; height: 100%; display: block; }
        
        #view-hint {
            position: absolute; bottom: 20px; right: 20px; color: rgba(255,255,255,0.5);
            font-family: monospace; font-size: 12px; pointer-events: none; z-index: 1000;
        }
    </style>
</head>
<body>
    <div id="main-container">
        <div id="left-panel">
            <h2 class="panel-title">
                <span class="app-brand">Embodied-SimLite | 具身智能数字孪生：SLAM建图与动态Nav2联合评测基准</span>
                🧩 模块一：感知与控制蓝图
            </h2>
            <canvas id="node-canvas"></canvas>
        </div>
        <div id="resizer"></div>
        <div id="right-panel">
            <h2 class="panel-title">🌐 模块二：Cyber-Physical 孪生观测域</h2>
            <div id="telemetry">
                <h3 style="margin-top:0; color:#fff; border-bottom:1px solid #555; padding-bottom:5px;">📡 遥测数据(Telemetry)</h3>
                <div class="tel-row truth"><span>真实坐标 X:</span><span id="true_x">0.00</span></div>
                <div class="tel-row truth"><span>真实坐标 Y:</span><span id="true_y">0.00</span></div>
                <div class="tel-row truth"><span>真实朝向 Yaw:</span><span id="true_yaw">0.00</span></div>
                <hr style="border: 0.5px solid #333;">
                <div class="tel-row odom"><span>里程计 X:</span><span id="odom_x">0.00</span></div>
                <div class="tel-row odom"><span>里程计 Y:</span><span id="odom_y">0.00</span></div>
                <div class="tel-row odom"><span>里程计 Yaw:</span><span id="odom_yaw">0.00</span></div>
                <div class="tel-row" style="color: #ffaa00; font-weight: bold; margin-top: 10px;"><span>累积误差:</span><span id="err_val">0.00m</span></div>
                <div class="tel-row" style="color: #ffaa00; font-weight: bold;"><span>🤖 推力 (L/R):</span><span id="motor_torque">0.0 / 0.0</span></div>
                <div class="tel-row" style="color: #ff4444; font-weight: bold; display: none;" id="warn_collision">⚠️ 接近物理边界！</div>
                <p>状态: <span id="wsStatus" style="color: yellow;">连接中...</span></p>
            </div>
            <div id="view-hint">左键: 旋转 | 右键: 平移 | 滚轮: 缩放 | R键: 视角归位</div>
            <div id="canvas-container"></div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/litegraph.js/build/litegraph.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>

    <script>
        window.simData = { x: -3.0, y: -3.0, yaw: Math.PI/2, ox: -3.0, oy: -3.0, oyaw: Math.PI/2, v: 0 };

        window.onload = function() {
            const wsUrl = `ws://${window.location.host}/ws/simulation`;
            const ws = new WebSocket(wsUrl);
            ws.onopen = () => document.getElementById('wsStatus').innerHTML = "<span style='color: lime;'>✅ 引擎在线</span>";

            var graph = new LGraph();
            var canvas = new LGraphCanvas("#node-canvas", graph);
            
            graph.onBeforeStep = function() {
                for (let i = 0; i < graph._nodes.length; ++i) {
                    if (graph._nodes[i].pos[1] < 170) graph._nodes[i].pos[1] = 170;
                }
            };
            
            function syncCanvasSize() {
                const lp = document.getElementById('left-panel');
                const cv = document.getElementById('node-canvas');
                cv.width = lp.clientWidth; cv.height = lp.clientHeight;
                if (canvas) { canvas.resize(); canvas.draw(true, true); }
            }

            function WatchNode() {
                this.addInput("X", "number"); this.addInput("Y", "number"); this.addInput("Yaw", "number");
                this.properties = { x: 0, y: 0, yaw: 0 };
                this.color = "#143"; this.bgcolor = "#264"; this.size = [160, 70]; this.title_text_color = "#00ffcc"; 
            }
            WatchNode.title = "👁️ 姿态监视器 (Pose)";
            WatchNode.prototype.onExecute = function() {
                this.properties.x = this.getInputData(0) || 0; this.properties.y = this.getInputData(1) || 0; this.properties.yaw = this.getInputData(2) || 0;
            };
            WatchNode.prototype.onDrawBackground = function(ctx) {
                if (this.flags.collapsed) return;
                ctx.fillStyle = "#00ffcc"; ctx.font = "bold 14px monospace";
                
                let x_val = (this.properties.x || 0).toFixed(2);
                let y_val = (this.properties.y || 0).toFixed(2);
                
                let yaw_deg = ((this.properties.yaw || 0) * 180 / Math.PI) % 360;
                if (yaw_deg > 180) yaw_deg -= 360;
                else if (yaw_deg < -180) yaw_deg += 360;
                
                ctx.fillText(`${x_val}`, 50, 25); 
                ctx.fillText(`${y_val}`, 50, 45); 
                ctx.fillText(`${yaw_deg.toFixed(1)}°`, 50, 65);
            };
            LiteGraph.registerNodeType("分析/监视器", WatchNode);

            function DynamicChassisNode() {
                this.addInput("左力矩", "number"); this.addInput("右力矩", "number");
                this.addInput("车体质量", "number"); this.addInput("滑移误差", "number");
                this.color = "#422"; this.bgcolor = "#633"; this.size = [200, 115]; this.title_text_color = "#ff7744"; 
            }
            DynamicChassisNode.title = "🚀 动力学底盘";
            DynamicChassisNode.prototype.onExecute = function() {
                if (ws.readyState === WebSocket.OPEN) {
                    let l = this.getInputData(0); let r = this.getInputData(1);
                    let payload = { mass: this.getInputData(2) || 1.0, noise: this.getInputData(3) || 0.0 };
                    if (l !== undefined) payload.left = l; if (r !== undefined) payload.right = r;
                    ws.send(JSON.stringify(payload));
                }
            };
            LiteGraph.registerNodeType("执行/动力学", DynamicChassisNode);

            function MotorNode() {
                this.addOutput("力矩", "number"); 
                this.properties = { value: 0 };
                this.addWidget("number", "推力", 0, (v)=>{ 
                    let val = Number(v); if (isNaN(val)) val = 0;
                    this.properties.value = Math.max(-20, Math.min(20, val)); 
                }, { precision: 2, min: -20, max: 20 });
                this.color = "#223"; this.size = [180, 60]; this.title_text_color = "#ffcc00";
            }
            MotorNode.title = "🎛️ 电机参数(手动档)";
            MotorNode.prototype.onExecute = function() { this.setOutputData(0, this.properties.value); };
            LiteGraph.registerNodeType("控制/驱动", MotorNode);

            function EnvNode() {
                this.addOutput("质量", "number"); this.addOutput("误差系数", "number");
                this.properties = { m: 1.0, noise: 0.05 };
                this.addWidget("number", "质量(kg)", 1.0, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 1.0;
                    this.properties.m = Math.max(0.1, val); 
                }, { precision: 2, min: 0.1, step: 0.1 });
                this.addWidget("number", "打滑误差", 0.05, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 0.05;
                    this.properties.noise = Math.max(0.0, Math.min(0.3, val));
                }, { precision: 2, min: 0.0, max: 0.3, step: 0.01 });
                this.size = [180, 90]; this.title_text_color = "#ff7744"; 
            }
            EnvNode.title = "⚖️ 环境与误差因子";
            EnvNode.prototype.onExecute = function() { this.setOutputData(0, this.properties.m); this.setOutputData(1, this.properties.noise); };
            LiteGraph.registerNodeType("环境/物理", EnvNode);

            function OdomNode() {
                this.addOutput("估计 X", "number"); this.addOutput("估计 Y", "number"); this.addOutput("估计 Yaw", "number");
                this.color = "#622"; this.bgcolor = "#833"; this.size = [180, 80]; this.title_text_color = "#00ffcc"; 
            }
            OdomNode.title = "⚙️ 轮式里程计(Odom)";
            OdomNode.prototype.onExecute = function() { this.setOutputData(0, window.simData.ox); this.setOutputData(1, window.simData.oy); this.setOutputData(2, window.simData.oyaw); };
            LiteGraph.registerNodeType("传感/里程计", OdomNode);

            function TruthNode() {
                this.addOutput("真实 X", "number"); this.addOutput("真实 Y", "number"); this.addOutput("真实 Yaw", "number");
                this.color = "#266"; this.bgcolor = "#388"; this.size = [180, 80]; this.title_text_color = "#00ffcc"; 
            }
            TruthNode.title = "🛰️ 真实位置(Truth)";
            TruthNode.prototype.onExecute = function() { this.setOutputData(0, window.simData.x); this.setOutputData(1, window.simData.y); this.setOutputData(2, window.simData.yaw); };
            LiteGraph.registerNodeType("传感/真实定位", TruthNode);

            function LidarNode() {
                this.addOutput("线束", "number"); 
                this.addOutput("探测距离", "number"); 
                this.properties = { rays: 360, range_max: 15.0, phase: 0.0, ccw: true };
                
                this.addWidget("number", "雷达线束", 360, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 360;
                    this.properties.rays = Math.floor(Math.max(72, Math.min(720, val)));
                }, { precision: 0, min: 72, max: 720, step: 10 });
                
                this.addWidget("number", "探测距离(m)", 15.0, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 15.0;
                    this.properties.range_max = Math.max(1.0, Math.min(30.0, val));
                }, { precision: 2, min: 1.0, max: 30.0, step: 0.5 });

                this.addWidget("number", "零度相位差(度)", 0, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 0.0;
                    this.properties.phase = val;
                }, { precision: 0, min: -360, max: 360, step: 90 });

                this.addWidget("toggle", "逆时针扫描(CCW)", true, (v)=>{
                    this.properties.ccw = !!v;
                });

                this.color = "#255"; this.bgcolor = "#366"; this.size = [230, 140]; this.title_text_color = "#00ffcc"; 
            }
            LidarNode.title = "📡 传感/雷达相控阵";
            LidarNode.prototype.onExecute = function() { 
                this.setOutputData(0, this.properties.rays); 
                this.setOutputData(1, this.properties.range_max); 
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ 
                        num_rays: this.properties.rays,
                        range_max: this.properties.range_max,
                        phase: this.properties.phase,
                        ccw: this.properties.ccw
                    })); 
                }
            };
            LiteGraph.registerNodeType("传感/激光雷达配置", LidarNode);

            function TargetNode() {
                this.addOutput("目标 X", "number"); this.addOutput("目标 Y", "number"); 
                this.properties = { x: -3.0, y: -3.0 }; 
                this.addWidget("number", "目标坐标 X", -3.0, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = -3.0;
                    this.properties.x = Math.max(-20, Math.min(20, val));
                }, { precision: 2, min: -20, max: 20 }); 
                this.addWidget("number", "目标坐标 Y", -3.0, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = -3.0;
                    this.properties.y = Math.max(-20, Math.min(20, val));
                }, { precision: 2, min: -20, max: 20 });
                this.color = "#225"; this.bgcolor = "#336"; this.size = [200, 80]; this.title_text_color = "#ffcc00"; 
            }
            TargetNode.title = "🚩 2D 导航目标点";
            TargetNode.prototype.onExecute = function() { this.setOutputData(0, this.properties.x); this.setOutputData(1, this.properties.y); };
            LiteGraph.registerNodeType("控制/目标点", TargetNode);

            function NavBrainNode() {
                this.addInput("目标 X", "number"); this.addInput("目标 Y", "number"); this.addInput("当前 X", "number"); this.addInput("当前 Y", "number"); this.addInput("当前 Yaw", "number");
                this.addOutput("左力矩", "number"); this.addOutput("右力矩", "number");
                this.properties = { Kp_v: 2.0, Kp_w: 5.0 };
                this.addWidget("number", "线速度增益 (Kp_v)", this.properties.Kp_v, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 2.0;
                    this.properties.Kp_v = Math.max(0.0, val);
                }, { precision: 2, min: 0, step: 0.1 }); 
                this.addWidget("number", "角速度增益 (Kp_w)", this.properties.Kp_w, (v)=>{
                    let val = Number(v); if (isNaN(val)) val = 5.0;
                    this.properties.Kp_w = Math.max(0.0, val);
                }, { precision: 2, min: 0, step: 0.1 });
                this.color = "#822"; this.bgcolor = "#a33"; this.size = [240, 160]; this.title_text_color = "#ffcc00"; 
            }
            NavBrainNode.title = "🧠 2D 运动学差速大脑";
            NavBrainNode.prototype.onExecute = function() {
                let tx = this.getInputData(0) || 0; let ty = this.getInputData(1) || 0; let cx = this.getInputData(2) || 0; let cy = this.getInputData(3) || 0; let cyaw = this.getInputData(4) || 0;
                let dx = tx - cx; let dy = ty - cy; let distance = Math.sqrt(dx*dx + dy*dy);
                let target_yaw = Math.atan2(dy, dx); let yaw_error = target_yaw - cyaw;
                while (yaw_error > Math.PI) yaw_error -= 2 * Math.PI; while (yaw_error < -Math.PI) yaw_error += 2 * Math.PI;
                let v_out = 0; let w_out = 0;
                if (distance > 0.1) { w_out = this.properties.Kp_w * yaw_error; if (Math.abs(yaw_error) < 0.5) v_out = this.properties.Kp_v * distance; }
                let left_torque = Math.max(-20, Math.min(20, v_out - w_out)); let right_torque = Math.max(-20, Math.min(20, v_out + w_out));
                this.setOutputData(0, left_torque); this.setOutputData(1, right_torque);
            };
            LiteGraph.registerNodeType("控制/2D导航计算", NavBrainNode);

            var nTarget = LiteGraph.createNode("控制/目标点"); nTarget.pos=[30, 170]; graph.add(nTarget);
            var nTruth = LiteGraph.createNode("传感/真实定位"); nTruth.pos=[30, 290]; graph.add(nTruth);
            var nOdom = LiteGraph.createNode("传感/里程计"); nOdom.pos=[30, 390]; graph.add(nOdom);
            var nLidar = LiteGraph.createNode("传感/激光雷达配置"); nLidar.pos=[30, 490]; graph.add(nLidar);
            var nE = LiteGraph.createNode("环境/物理"); nE.pos=[30, 650]; graph.add(nE);

            var nNavBrain = LiteGraph.createNode("控制/2D导航计算"); nNavBrain.pos=[340, 170]; graph.add(nNavBrain);
            var nB = LiteGraph.createNode("执行/动力学"); nB.pos=[340, 360]; graph.add(nB);
            var nL = LiteGraph.createNode("控制/驱动"); nL.pos=[340, 500]; graph.add(nL);
            var nR = LiteGraph.createNode("控制/驱动"); nR.pos=[340, 580]; graph.add(nR);
            var nWatchTruth = LiteGraph.createNode("分析/监视器"); nWatchTruth.pos=[340, 660]; graph.add(nWatchTruth);
            var nWatchOdom = LiteGraph.createNode("分析/监视器"); nWatchOdom.pos=[340, 750]; graph.add(nWatchOdom);

            nTarget.connect(0, nNavBrain, 0); nTarget.connect(1, nNavBrain, 1);
            nTruth.connect(0, nNavBrain, 2); nTruth.connect(1, nNavBrain, 3); nTruth.connect(2, nNavBrain, 4);
            nE.connect(0, nB, 2); nE.connect(1, nB, 3);
            nTruth.connect(0, nWatchTruth, 0); nTruth.connect(1, nWatchTruth, 1); nTruth.connect(2, nWatchTruth, 2);
            nOdom.connect(0, nWatchOdom, 0); nOdom.connect(1, nWatchOdom, 1); nOdom.connect(2, nWatchOdom, 2);

            graph.start();

            // ==========================================
            // 3D 渲染与控制
            // ==========================================
            const rp = document.getElementById('right-panel');
            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(45, rp.clientWidth/rp.clientHeight, 0.1, 1000);
            
            const initialCameraPos = new THREE.Vector3(0, -40, 45);
            const initialCameraTarget = new THREE.Vector3(0, 0, 0);
            
            camera.position.copy(initialCameraPos);
            camera.lookAt(initialCameraTarget);
            
            const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(rp.clientWidth, rp.clientHeight);
            document.getElementById('canvas-container').appendChild(renderer.domElement);
            
            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;       
            controls.dampingFactor = 0.05;
            controls.screenSpacePanning = true;  
            controls.minDistance = 5;            
            controls.maxDistance = 150;          
            controls.maxPolarAngle = Math.PI / 2 - 0.05; 
            controls.target.copy(initialCameraTarget);

            scene.add(new THREE.AmbientLight(0xffffff, 0.7));
            const light = new THREE.DirectionalLight(0xffffff, 0.8); light.position.set(5, 10, 10); scene.add(light);
            
            const grid = new THREE.GridHelper(200, 200, 0x444444, 0x222222); 
            grid.rotation.x = Math.PI/2; 
            scene.add(grid);

            const obstacles = [];
            const wallMat = new THREE.MeshLambertMaterial({color: 0x555577});
            
            function addWall(w, h, d, x, y) { 
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), wallMat); 
                mesh.position.set(x, y, d/2); 
                scene.add(mesh); obstacles.push(mesh); 
            }
            
            // ==========================================
            // 🎯 【六维复合压测场：40x40 拓扑重构】
            // ==========================================
            // 外墙
            addWall(44, 2, 1.5, 0, 21);   
            addWall(44, 2, 1.5, 0, -21);  
            addWall(2, 40, 1.5, 21, 0);   
            addWall(2, 40, 1.5, -21, 0);  

            // [场景 1] SLAM 纵向退化：死亡长廊
            addWall(1, 28, 1.5, 10, 0);
            addWall(1, 28, 1.5, 15, 0);
            addWall(5, 1, 1.5, 12.5, 14.5); 

            // [场景 2] SLAM 畸变与闭环：混沌迷宫
            addWall(6, 1, 1.5, -12, 12);
            addWall(1, 8, 1.5, -15, 8.5);
            addWall(6, 1, 1.5, -12, 5);
            addWall(1, 6, 1.5, -9, 8);
            addWall(4, 1, 1.5, -7, 11);

            // [场景 4] Nav2 局部死锁：绝望 U 型谷
            addWall(6, 1, 1.5, -12, -10);
            addWall(1, 6, 1.5, -15, -13);
            addWall(6, 1, 1.5, -12, -16);
            
            // [场景 5] Nav2 弹性皮筋微操：极限一线天
            addWall(4, 1, 1.5, 2, -2);
            addWall(4, 1, 1.5, -2, -4);
            addWall(4, 1, 1.5, 2, -6);
            addWall(1, 4, 1.5, 4.5, -4);
            
            // ==========================================

            const robotGroup = new THREE.Group();
            
            const chassisGeo = new THREE.BoxGeometry(0.8, 0.6, 0.2);
            const chassis = new THREE.Mesh(chassisGeo, new THREE.MeshLambertMaterial({color: 0x00cc88}));
            chassis.position.set(0, 0, 0.15); 
            robotGroup.add(chassis);
            
            const wheelGeo = new THREE.CylinderGeometry(0.15, 0.15, 0.1, 16);
            const wheelMat = new THREE.MeshLambertMaterial({color: 0x222222});
            
            const leftWheel = new THREE.Mesh(wheelGeo, wheelMat); 
            leftWheel.rotation.x = Math.PI / 2; 
            leftWheel.position.set(0, 0.35, 0.15); 
            robotGroup.add(leftWheel);
            
            const rightWheel = new THREE.Mesh(wheelGeo, wheelMat); 
            rightWheel.rotation.x = Math.PI / 2; 
            rightWheel.position.set(0, -0.35, 0.15); 
            robotGroup.add(rightWheel);
            
            const lidarMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.12, 16), new THREE.MeshLambertMaterial({color: 0x00aaff})); 
            lidarMesh.position.set(0, 0, 0.31); 
            robotGroup.add(lidarMesh);
            
            const arrowShape = new THREE.Shape(); 
            arrowShape.moveTo(0.25, 0);       
            arrowShape.lineTo(-0.15, 0.2);    
            arrowShape.lineTo(-0.05, 0);      
            arrowShape.lineTo(-0.15, -0.2);   
            arrowShape.lineTo(0.25, 0);       
            
            const arrowGeo = new THREE.ShapeGeometry(arrowShape); 
            const arrow = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({color: 0xffffff})); 
            arrow.position.set(0.1, 0, 0.26); 
            robotGroup.add(arrow);
            scene.add(robotGroup);

            const ghostGroup = new THREE.Group();
            const gChassis = new THREE.Mesh(chassisGeo, new THREE.MeshLambertMaterial({color: 0xff3333, transparent: true, opacity: 0.5})); 
            gChassis.position.set(0, 0, 0.15); 
            ghostGroup.add(gChassis);
            
            const gWheelMat = new THREE.MeshLambertMaterial({color: 0x442222, transparent: true, opacity: 0.5});
            const gLeftWheel = new THREE.Mesh(wheelGeo, gWheelMat); 
            gLeftWheel.rotation.x = Math.PI / 2; 
            gLeftWheel.position.set(0, 0.35, 0.15); 
            ghostGroup.add(gLeftWheel);
            
            const gRightWheel = new THREE.Mesh(wheelGeo, gWheelMat); 
            gRightWheel.rotation.x = Math.PI / 2; 
            gRightWheel.position.set(0, -0.35, 0.15); 
            ghostGroup.add(gRightWheel);
            
            const gArrow = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({color: 0xffaaaa, transparent: true, opacity: 0.6})); 
            gArrow.position.set(0.1, 0, 0.26); 
            ghostGroup.add(gArrow);
            scene.add(ghostGroup);

            const dynObsMeshes = {};
            const dynObsMat = new THREE.MeshLambertMaterial({color: 0xff6600}); 

            const lidarMat = new THREE.LineBasicMaterial({ color: 0x00ffff, transparent: true, opacity: 0.6 });
            const lidarGeo = new THREE.BufferGeometry(); 
            const lidarLines = new THREE.LineSegments(lidarGeo, lidarMat); 
            scene.add(lidarLines); 

            const raycaster = new THREE.Raycaster();
            let numRays = 360; 
            let rangeMax = 15.0; 
            let phaseOffset = 0.0;
            let isCCW = true;

            ws.onmessage = (e) => {
                const d = JSON.parse(e.data);
                window.simData = d; 
                if (d.num_rays && d.num_rays !== numRays) numRays = d.num_rays;
                if (d.range_max && d.range_max !== rangeMax) rangeMax = d.range_max;
                if (d.phase !== undefined) phaseOffset = d.phase;
                if (d.ccw !== undefined) isCCW = d.ccw;
                
                robotGroup.position.set(d.x, d.y, 0); robotGroup.rotation.z = d.yaw;
                ghostGroup.position.set(d.ox, d.oy, 0); ghostGroup.rotation.z = d.oyaw;
                
                if (d.dyn_obs) {
                    d.dyn_obs.forEach(obs => {
                        if (!dynObsMeshes[obs.id]) {
                            const mesh = new THREE.Mesh(new THREE.BoxGeometry(obs.w, obs.h, 1.5), dynObsMat);
                            scene.add(mesh);
                            obstacles.push(mesh);
                            dynObsMeshes[obs.id] = mesh;
                        }
                        dynObsMeshes[obs.id].position.set(obs.x, obs.y, 0.75);
                        dynObsMeshes[obs.id].updateMatrixWorld(); 
                    });
                }

                const err = Math.sqrt(Math.pow(d.x - d.ox, 2) + Math.pow(d.y - d.oy, 2));

                document.getElementById('true_x').innerText = d.x.toFixed(2) + ' m';
                document.getElementById('true_y').innerText = d.y.toFixed(2) + ' m';
                let ty = (d.yaw * 180 / Math.PI) % 360; if (ty > 180) ty -= 360; else if (ty < -180) ty += 360;
                document.getElementById('true_yaw').innerText = ty.toFixed(1) + '°';
                
                document.getElementById('odom_x').innerText = d.ox.toFixed(2) + ' m';
                document.getElementById('odom_y').innerText = d.oy.toFixed(2) + ' m';
                let oy = (d.oyaw * 180 / Math.PI) % 360; if (oy > 180) oy -= 360; else if (oy < -180) oy += 360;
                document.getElementById('odom_yaw').innerText = oy.toFixed(1) + '°';
                
                document.getElementById('err_val').innerText = err.toFixed(3) + ' m';
                document.getElementById('motor_torque').innerText = `${(d.f_l || 0).toFixed(2)} / ${(d.f_r || 0).toFixed(2)}`;
                
                document.getElementById('warn_collision').style.display = (d.col_f || d.col_r) ? 'flex' : 'none';
            };

            function performLidarScan() {
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                
                const positions = []; 
                const origin = new THREE.Vector3(robotGroup.position.x, robotGroup.position.y, 0.5); 
                const lidar_distances = []; 
                
                let minFrontDist = rangeMax; 
                let isFrontClipping = false;
                let isRearClipping = false;
                
                let direction = isCCW ? 1 : -1;
                let phaseRad = (phaseOffset * Math.PI) / 180.0;

                for (let i = 0; i < numRays; i++) {
                    let trueLocalAngle = direction * (i * 2 * Math.PI / numRays) + phaseRad;
                    while (trueLocalAngle > Math.PI) trueLocalAngle -= 2 * Math.PI;
                    while (trueLocalAngle < -Math.PI) trueLocalAngle += 2 * Math.PI;

                    const angle = robotGroup.rotation.z + trueLocalAngle;
                    const dir = new THREE.Vector3(Math.cos(angle), Math.sin(angle), 0).normalize();
                    raycaster.set(origin, dir);
                    const intersects = raycaster.intersectObjects(obstacles);
                    
                    positions.push(origin.x, origin.y, origin.z); 
                    
                    if (intersects.length > 0 && intersects[0].distance <= rangeMax) {
                        let dist = intersects[0].distance;
                        positions.push(intersects[0].point.x, intersects[0].point.y, intersects[0].point.z);
                        lidar_distances.push(dist);
                        
                        if (Math.abs(trueLocalAngle) < Math.PI / 2.5) {
                            let forwardDist = dist * Math.cos(trueLocalAngle);
                            if (forwardDist < minFrontDist) minFrontDist = forwardDist;
                        }
                        if (dist < 0.38) {
                            if (Math.abs(trueLocalAngle) < Math.PI / 2) isFrontClipping = true; else isRearClipping = true;
                        }
                    } else {
                        positions.push(origin.x + dir.x * rangeMax, origin.y + dir.y * rangeMax, origin.z); 
                        lidar_distances.push(999.0); 
                    }
                }
                
                lidarGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

                const compressed_lidar = lidar_distances.map(d => Number(d.toFixed(3)));
                ws.send(JSON.stringify({ 
                    lidar: compressed_lidar, 
                    lidar_stamp: Date.now(), 
                    col_f: (minFrontDist < 0.45 || isFrontClipping), 
                    col_r: isRearClipping 
                }));
            }

            function animate() {
                requestAnimationFrame(animate);
                controls.update(); 
                renderer.render(scene, camera);
            }
            animate();

            const workerCode = `
                let timer;
                self.onmessage = function(e) {
                    if (e.data === 'start') {
                        timer = setInterval(() => self.postMessage('tick'), 100); 
                    }
                };
            `;
            const blob = new Blob([workerCode], {type: 'application/javascript'});
            const worker = new Worker(URL.createObjectURL(blob));
            
            worker.onmessage = function(e) {
                if (e.data === 'tick') {
                    performLidarScan();
                    if ((document.hidden || document.visibilityState !== 'visible') && typeof graph !== 'undefined') {
                        graph.runStep(1/10, false);
                    }
                }
            };
            worker.postMessage('start');

            window.addEventListener('keydown', (e) => {
                if(e.target.tagName.toLowerCase() === 'input') return;
                if (e.key.toLowerCase() === 'r') {
                    camera.position.copy(initialCameraPos);
                    controls.target.copy(initialCameraTarget);
                    controls.update();
                }
            });

            const resizer = document.getElementById('resizer'); const leftPanel = document.getElementById('left-panel'); let isResizing = false;
            resizer.addEventListener('mousedown', () => { isResizing = true; document.body.style.cursor = 'ew-resize'; });
            window.addEventListener('mousemove', (e) => {
                if (!isResizing) return; let percent = (e.clientX / window.innerWidth) * 100;
                if (percent > 15 && percent < 85) { leftPanel.style.flexBasis = percent + '%'; syncCanvasSize(); camera.aspect = rp.clientWidth / rp.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(rp.clientWidth, rp.clientHeight); }
            });
            window.addEventListener('mouseup', () => { isResizing = false; document.body.style.cursor = 'default'; });
            window.addEventListener('resize', () => { syncCanvasSize(); camera.aspect = rp.clientWidth / rp.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(rp.clientWidth, rp.clientHeight); });
            syncCanvasSize();
        };
    </script>
</body>
</html>
"""

@app.get("/")
async def get_webpage(): return HTMLResponse(html_content)

state = { 
    "x": -3.0, "y": -3.0, "yaw": math.pi/2, "ox": -3.0, "oy": -3.0, "oyaw": math.pi/2, 
    "v": 0.0, "w": 0.0, "mass": 1.0, "noise": 0.05, "f_l": 0.0, "f_r": 0.0, 
    "lidar": [], "lidar_stamp": 0, "num_rays": 360, "range_max": 15.0, 
    "col_f": False, "col_r": False, "phase": 0.0, "ccw": True,
    "dyn_obs": [
        {"id": 0, "x": -5.0, "y": -8.0, "vx": 4.0, "vy": 0.0, "w": 1.0, "h": 1.0, "min_x": -15.0, "max_x": 5.0, "min_y": -8.0, "max_y": -8.0},
        {"id": 1, "x": 12.5, "y": 0.0, "vx": 0.0, "vy": 2.5, "w": 1.5, "h": 1.5, "min_x": 12.5, "max_x": 12.5, "min_y": -18.0, "max_y": 12.0},
        {"id": 2, "x": -4.0, "y": 15.0, "vx": -1.5, "vy": -1.5, "w": 1.0, "h": 1.0, "min_x": -18.0, "max_x": -2.0, "min_y": 12.0, "max_y": 18.0}
    ]
}

# 🎯【终极修复 2】：Python 物理刚体池与 JS 视觉墙面坐标的 1:1 绝对对齐！
# 彻底根除因“坐标不匹配”导致的小车能被拦住，但雷达发射源却卡进墙体内部，引发 999.0 击穿地图的 Bug！
walls = [
    (-22.0, 22.0, 20.0, 22.0),    
    (-22.0, 22.0, -22.0, -20.0),  
    (20.0, 22.0, -20.0, 20.0),    
    (-22.0, -20.0, -20.0, 20.0),  
    
    (9.5, 10.5, -14.0, 14.0),     
    (14.5, 15.5, -14.0, 14.0),    
    (10.0, 15.0, 14.0, 15.0),     
    
    (-15.0, -9.0, 11.5, 12.5),    
    (-15.5, -14.5, 4.5, 12.5),    
    (-15.0, -9.0, 4.5, 5.5),      
    (-9.5, -8.5, 5.0, 11.0),      
    (-9.0, -5.0, 10.5, 11.5),     
    
    (-15.0, -9.0, -10.5, -9.5),   
    (-15.5, -14.5, -16.0, -10.0), 
    (-15.0, -9.0, -16.5, -15.5),  
    
    (0.0, 4.0, -2.5, -1.5),       
    (-4.0, 0.0, -4.5, -3.5),      
    (0.0, 4.0, -6.5, -5.5),       
    (4.0, 5.0, -6.0, -2.0)        
]

def resolve_collision(x, y, dyn_obstacles):
    r = 0.30 
    hit = False
    for _ in range(2):
        for wx1, wx2, wy1, wy2 in walls:
            ex1, ex2, ey1, ey2 = wx1 - r, wx2 + r, wy1 - r, wy2 + r
            if ex1 < x < ex2 and ey1 < y < ey2:
                dx1, dx2 = x - ex1, ex2 - x
                dy1, dy2 = y - ey1, ey2 - y
                m = min(dx1, dx2, dy1, dy2)
                if m == dx1: x = ex1
                elif m == dx2: x = ex2
                elif m == dy1: y = ey1
                else: y = ey2
                hit = True
                
        for obs in dyn_obstacles:
            ex1 = obs["x"] - obs["w"]/2 - r
            ex2 = obs["x"] + obs["w"]/2 + r
            ey1 = obs["y"] - obs["h"]/2 - r
            ey2 = obs["y"] + obs["h"]/2 + r
            if ex1 < x < ex2 and ey1 < y < ey2:
                dx1, dx2 = x - ex1, ex2 - x
                dy1, dy2 = y - ey1, ey2 - y
                m = min(dx1, dx2, dy1, dy2)
                if m == dx1: x = ex1
                elif m == dx2: x = ex2
                elif m == dy1: y = ey1
                else: y = ey2
                hit = True
                
    return x, y, hit

async def physics_loop():
    global state
    dt = 1.0 / 60.0  
    while True:
        for obs in state["dyn_obs"]:
            nx = obs["x"] + obs["vx"] * dt
            ny = obs["y"] + obs["vy"] * dt
            
            if nx <= obs["min_x"] or nx >= obs["max_x"]:
                obs["vx"] *= -1
                nx = obs["x"] + obs["vx"] * dt
            if ny <= obs["min_y"] or ny >= obs["max_y"]:
                obs["vy"] *= -1
                ny = obs["y"] + obs["vy"] * dt
                
            rw, rh = obs["w"] / 2.0, obs["h"] / 2.0
            hit_x, hit_y = False, False
            for wx1, wx2, wy1, wy2 in walls:
                if wx1 - rw < nx < wx2 + rw and wy1 - rh < obs["y"] < wy2 + rh:
                    hit_x = True
                if wx1 - rw < obs["x"] < wx2 + rw and wy1 - rh < ny < wy2 + rh:
                    hit_y = True
                    
            if hit_x:
                obs["vx"] *= -1
                nx = obs["x"] + obs["vx"] * dt
            if hit_y:
                obs["vy"] *= -1
                ny = obs["y"] + obs["vy"] * dt
                
            obs["x"] = nx
            obs["y"] = ny

        force = (state["f_l"] + state["f_r"])
        torque = (state["f_r"] - state["f_l"]) * 0.5
        accel = force / max(0.1, state["mass"])
        alpha = torque / max(0.1, state["mass"] * 0.5)
        
        # 🎯【终极修复 1】：引入电机制动抱死逻辑 (Active Braking)
        # 当 Nav2 指挥推力归零时，无情扼杀小车的滑行惯性，告别 Overshoot 向前冲的现象！
        if abs(force) < 0.001:
            state["v"] *= 0.5
        else:
            state["v"] = (state["v"] + accel * dt) * 0.95 
            
        if abs(torque) < 0.001:
            state["w"] *= 0.5
        else:
            state["w"] = (state["w"] + alpha * dt) * 0.95
        
        state["yaw"] += state["w"] * dt
        state["x"] += state["v"] * math.cos(state["yaw"]) * dt
        state["y"] += state["v"] * math.sin(state["yaw"]) * dt
        
        state["x"] = max(-19.6, min(19.6, state["x"]))
        state["y"] = max(-19.6, min(19.6, state["y"]))
        
        state["x"], state["y"], hit = resolve_collision(state["x"], state["y"], state["dyn_obs"])
        if hit: 
            state["v"] *= 0.5 
            state["w"] *= 0.5
        
        noisy_v = state["v"] + random.gauss(0, abs(state["v"]) * state["noise"])
        noisy_w = state["w"] + random.gauss(0, abs(state["w"]) * state["noise"])
        
        state["oyaw"] += noisy_w * dt
        state["ox"] += noisy_v * math.cos(state["oyaw"]) * dt
        state["oy"] += noisy_v * math.sin(state["oyaw"]) * dt
        
        state["ox"], state["oy"], hit_o = resolve_collision(state["ox"], state["oy"], state["dyn_obs"])
        
        await asyncio.sleep(dt)

@app.on_event("startup")
async def startup_event(): asyncio.create_task(physics_loop())

@app.websocket("/ws/simulation")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    async def recv():
        try:
            while True:
                data = json.loads(await websocket.receive_text())
                if "lidar" in data:
                    state["lidar"] = data["lidar"]
                    state["lidar_stamp"] = data.get("lidar_stamp", 0)
                    if "col_f" in data: state["col_f"] = data["col_f"]
                    if "col_r" in data: state["col_r"] = data["col_r"]
                else:
                    if "left" in data:
                        state["f_l"] = float(data["left"]) if data["left"] is not None else 0.0
                    if "right" in data:
                        state["f_r"] = float(data["right"]) if data["right"] is not None else 0.0
                    if "mass" in data:
                        state["mass"] = float(data["mass"]) if data["mass"] is not None else 1.0
                    if "noise" in data:
                        state["noise"] = float(data["noise"]) if data["noise"] is not None else 0.0
                    if "num_rays" in data: 
                        state["num_rays"] = data["num_rays"]
                    if "range_max" in data: 
                        state["range_max"] = data["range_max"]
                    if "phase" in data:
                        state["phase"] = float(data["phase"]) if data["phase"] is not None else 0.0
                    if "ccw" in data:
                        state["ccw"] = bool(data["ccw"])
        except: pass
    rt = asyncio.create_task(recv())
    try:
        while True:
            payload = { 
                "x": state["x"], "y": state["y"], "yaw": state["yaw"], 
                "ox": state["ox"], "oy": state["oy"], "oyaw": state["oyaw"], 
                "v": state["v"], "num_rays": state["num_rays"], "range_max": state["range_max"],
                "phase": state["phase"], "ccw": state["ccw"],
                "f_l": state["f_l"], "f_r": state["f_r"], 
                "col_f": state["col_f"], "col_r": state["col_r"],
                "dyn_obs": state["dyn_obs"]
            }
            if state["lidar"]: 
                payload["lidar"] = state["lidar"]
                payload["lidar_stamp"] = state["lidar_stamp"]
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(1/30.) 
    finally: rt.cancel()

if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8000)