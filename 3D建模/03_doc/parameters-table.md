# 比邻AI · 3D 捏脸参数总表（唯一契约）

- 版本：`params-table-1.0.0`　生成日期：2026-09-30
- 分区条数：A=17、B=8、C=18、D=10、E=12、F=5、G=12、H=10、I=7、J=3　合计 **102** 条（规格书要求 ≥100 条）
- 通道分布：asset=6、bone=6、material=27、morph=63
- 通道图例：`bone`=骨骼驱动；`morph`=BlendShape 驱动（编辑期 shape_*，交付期烘焙进顶点）；`material`=材质驱动；`asset`=资产切换
- 默认值约定：所有连续参数默认 `0` = 基准模型（同年龄段的普通人）；材质/资产类参数默认见「默认」列。
- `morph` 通道的双向参数绑定 **两个** target（`shape_<key>_up` / `shape_<key>_dn`），滑杆范围 -1~+1；单向增强类参数绑定单个 `shape_<key>`，范围 0~1。端侧不得向 morph 权重写负值；换算与实测幅度见 `shape-namespace-map.json`。
- `老人可用性` 列（规格书 §9 康养裁剪）为 `client/care-trim.js` 结论的投影：**保留 79 / 弱化 20 / 不做 3**（三类之和 = 102，其中 15 条为「保留并强化」）。逐条理由写在该模块的裁剪表里；本列改由 `_mk_params_el.mjs` 生成与校验，手工改表会被 `--check` 判为漂移。

## 参数总表

| 分区 | 中文名 | 参数 key | 通道 | 绑定目标 | 类型 | 范围 | 默认 | 联动 | 老人可用性 |
|---|---|---|---|---|---|---|---|---|---|
| A 脸型（轮廓） | 脸宽 | `face_width` | `morph` | `shape_face_width_up / shape_face_width_dn` | `weight` | -1~+1 | 0 | face_fat | 保留 |
| A 脸型（轮廓） | 脸长 | `face_length` | `morph` | `shape_face_length_up / shape_face_length_dn` | `weight` | -1~+1 | 0 | chin_length | 保留 |
| A 脸型（轮廓） | 颧骨高低 | `cheekbone_height` | `morph` | `shape_cheekbone_height_up / shape_cheekbone_height_dn` | `weight` | -1~+1 | 0 | cheek_fullness | 保留 |
| A 脸型（轮廓） | 颧骨宽窄 | `cheekbone_width` | `morph` | `shape_cheekbone_width_up / shape_cheekbone_width_dn` | `weight` | -1~+1 | 0 | face_width | 保留 |
| A 脸型（轮廓） | 脸颊饱满 | `cheek_fullness` | `morph` | `shape_cheek_fullness_up / shape_cheek_fullness_dn` | `weight` | -1~+1 | 0 | age_overall | 保留 |
| A 脸型（轮廓） | 太阳穴宽窄 | `temple_width` | `morph` | `shape_temple_width_up / shape_temple_width_dn` | `weight` | -1~+1 | 0 | forehead_width | 保留 |
| A 脸型（轮廓） | 下颌宽窄 | `jaw_width` | `morph` | `shape_jaw_width_up / shape_jaw_width_dn` | `weight` | -1~+1 | 0 | chin_width | 保留 |
| A 脸型（轮廓） | 下颌角 | `jaw_angle` | `morph` | `shape_jaw_angle_up / shape_jaw_angle_dn` | `weight` | -1~+1 | 0 | jaw_width | 保留 |
| A 脸型（轮廓） | 下巴长度 | `chin_length` | `morph` | `shape_chin_length_up / shape_chin_length_dn` | `weight` | -1~+1 | 0 | face_length | 保留 |
| A 脸型（轮廓） | 下巴前突 | `chin_protrusion` | `morph` | `shape_chin_protrusion_up / shape_chin_protrusion_dn` | `weight` | -1~+1 | 0 | chin_length | 弱化 |
| A 脸型（轮廓） | 下巴宽窄 | `chin_width` | `morph` | `shape_chin_width_up / shape_chin_width_dn` | `weight` | -1~+1 | 0 | jaw_width | 保留 |
| A 脸型（轮廓） | 下巴沟 | `chin_cleft` | `morph` | `shape_chin_cleft` | `weight` | 0~1 | 0 | - | 保留 |
| A 脸型（轮廓） | 额头高低 | `forehead_height` | `morph` | `shape_forehead_height_up / shape_forehead_height_dn` | `weight` | -1~+1 | 0 | face_length | 保留 |
| A 脸型（轮廓） | 额头宽窄 | `forehead_width` | `morph` | `shape_forehead_width_up / shape_forehead_width_dn` | `weight` | -1~+1 | 0 | temple_width | 保留 |
| A 脸型（轮廓） | 面部脂肪 | `face_fat` | `morph` | `shape_face_fat_up / shape_face_fat_dn` | `weight` | -1~+1 | 0 | age_overall | 弱化 |
| A 脸型（轮廓） | 脖子粗细 | `neck_thickness` | `bone` | `neck` | `scale` | 0.85~1.15 | 1.0 | shoulder_width | 保留 |
| A 脸型（轮廓） | 喉结 | `throat` | `morph` | `shape_throat_up / shape_throat_dn` | `weight` | -1~+1 | 0 | neck_thickness | 保留 |
| B 眉毛 | 眉型 | `brow_shape` | `asset` | `brow_style` | `enum` | 10 款 | 自然平眉 | brow_angle | 保留 |
| B 眉毛 | 浓密度 | `brow_density` | `material` | `brow_alpha` | `weight` | 0~1 | 0.5 | brow_color | 保留 |
| B 眉毛 | 高低 | `brow_height` | `morph` | `shape_brow_height_up / shape_brow_height_dn` | `weight` | -1~+1 | 0 | brow_angle | 保留 |
| B 眉毛 | 眉间距 | `brow_spacing` | `morph` | `shape_brow_spacing_up / shape_brow_spacing_dn` | `weight` | -1~+1 | 0 | brow_height | 保留 |
| B 眉毛 | 眉峰高度 | `brow_peak` | `morph` | `shape_brow_peak_up / shape_brow_peak_dn` | `weight` | -1~+1 | 0 | brow_angle | 保留 |
| B 眉毛 | 眉尾长短 | `brow_tail` | `morph` | `shape_brow_tail_up / shape_brow_tail_dn` | `weight` | -1~+1 | 0 | brow_shape | 保留 |
| B 眉毛 | 倾斜角度 | `brow_angle` | `morph` | `shape_brow_angle_up / shape_brow_angle_dn` | `weight` | -1~+1 | 0 | brow_height | 保留 |
| B 眉毛 | 眉色 | `brow_color` | `material` | `brow_color` | `color` | 色板 10 档 | 自然黑 | hair_color | 保留 |
| C 眼睛 | 眼睛大小 | `eye_size` | `morph` | `shape_eye_size_up / shape_eye_size_dn` | `weight` | -1~+1 | 0 | eye_width | 保留 |
| C 眼睛 | 眼睛高低 | `eye_height` | `morph` | `shape_eye_height_up / shape_eye_height_dn` | `weight` | -1~+1 | 0 | brow_height | 保留 |
| C 眼睛 | 眼睛宽度 | `eye_width` | `morph` | `shape_eye_width_up / shape_eye_width_dn` | `weight` | -1~+1 | 0 | eye_tilt | 保留 |
| C 眼睛 | 眼距 | `eye_spacing` | `bone` | `eye.L/eye.R` | `translate` | +/-3 mm | 0 | eye_size（约束） | 保留 |
| C 眼睛 | 内眼角 | `eye_inner_corner` | `morph` | `shape_eye_inner_corner_up / shape_eye_inner_corner_dn` | `weight` | -1~+1 | 0 | eye_spacing（约束） | 保留 |
| C 眼睛 | 外眼角 | `eye_outer_corner` | `morph` | `shape_eye_outer_corner_up / shape_eye_outer_corner_dn` | `weight` | -1~+1 | 0 | eye_tilt | 弱化 |
| C 眼睛 | 单双眼皮 | `eye_lid_type` | `morph` | `shape_eye_lid_type` | `enum` | 3 档 | 双眼皮 | lid_crease_depth | 保留 |
| C 眼睛 | 上眼皮褶皱深度 | `lid_crease_depth` | `morph` | `shape_lid_crease_depth_up / shape_lid_crease_depth_dn` | `weight` | 0~1 | 0 | eye_lid_type | 保留 |
| C 眼睛 | 眼袋 | `eye_bag` | `morph` | `shape_eye_bag` | `weight` | 0~1 | 0 | age_overall | 保留 |
| C 眼睛 | 卧蚕 | `eye_aegyo` | `morph` | `shape_eye_aegyo` | `weight` | 0~1 | 0 | eye_bag | 弱化 |
| C 眼睛 | 眼窝深浅 | `eye_socket_depth` | `morph` | `shape_eye_socket_depth_up / shape_eye_socket_depth_dn` | `weight` | -1~+1 | 0 | age_overall | 保留 |
| C 眼睛 | 眼睛倾斜 | `eye_tilt` | `morph` | `shape_eye_tilt_up / shape_eye_tilt_dn` | `weight` | -1~+1 | 0 | eye_outer_corner | 弱化 |
| C 眼睛 | 瞳孔大小 | `pupil_size` | `material` | `iris_pupil_scale` | `weight` | 0~1 | 0.5 | iris_size | 保留 |
| C 眼睛 | 虹膜大小 | `iris_size` | `material` | `iris_radius_scale` | `weight` | 0~1 | 0.5 | pupil_size | 保留 |
| C 眼睛 | 瞳孔颜色 | `pupil_color` | `material` | `iris_color` | `color` | 自然色板 6 档 | 深棕 | iris_size | 弱化 |
| C 眼睛 | 睫毛长度 | `lash_length` | `asset` | `lash_mesh` | `enum` | 3 档 | 自然 | lash_density | 保留 |
| C 眼睛 | 睫毛浓密度 | `lash_density` | `material` | `lash_alpha` | `weight` | 0~1 | 0.5 | lash_length | 保留 |
| C 眼睛 | 眼球湿润度 | `eye_wetness` | `material` | `eye_roughness` | `weight` | 0~1 | 0.5 | - | 保留 |
| D 鼻子 | 鼻长 | `nose_length` | `morph` | `shape_nose_length_up / shape_nose_length_dn` | `weight` | -1~+1 | 0 | nose_root_depth | 保留 |
| D 鼻子 | 鼻梁高度 | `nose_bridge_height` | `morph` | `shape_nose_bridge_height_up / shape_nose_bridge_height_dn` | `weight` | -1~+1 | 0 | nose_bridge_curve | 保留 |
| D 鼻子 | 鼻梁宽度 | `nose_bridge_width` | `morph` | `shape_nose_bridge_width_up / shape_nose_bridge_width_dn` | `weight` | -1~+1 | 0 | nose_length | 保留 |
| D 鼻子 | 鼻梁弧度 | `nose_bridge_curve` | `morph` | `shape_nose_bridge_curve_up / shape_nose_bridge_curve_dn` | `weight` | -1~+1 | 0 | nose_bridge_height | 保留 |
| D 鼻子 | 鼻头大小 | `nose_tip_size` | `morph` | `shape_nose_tip_size_up / shape_nose_tip_size_dn` | `weight` | -1~+1 | 0 | nose_tip_upturn | 保留 |
| D 鼻子 | 鼻尖上翘 | `nose_tip_upturn` | `morph` | `shape_nose_tip_upturn_up / shape_nose_tip_upturn_dn` | `weight` | -1~+1 | 0 | nose_tip_size | 弱化 |
| D 鼻子 | 鼻翼宽度 | `nostril_width` | `morph` | `shape_nostril_width_up / shape_nostril_width_dn` | `weight` | -1~+1 | 0 | nostril_size | 保留 |
| D 鼻子 | 鼻翼高低 | `nostril_height` | `morph` | `shape_nostril_height_up / shape_nostril_height_dn` | `weight` | -1~+1 | 0 | nose_tip_upturn | 保留 |
| D 鼻子 | 鼻孔大小 | `nostril_size` | `morph` | `shape_nostril_size_up / shape_nostril_size_dn` | `weight` | -1~+1 | 0 | nostril_width | 保留 |
| D 鼻子 | 鼻根深浅 | `nose_root_depth` | `morph` | `shape_nose_root_depth_up / shape_nose_root_depth_dn` | `weight` | -1~+1 | 0 | nose_length | 保留 |
| E 嘴巴 | 嘴巴宽度 | `mouth_width` | `morph` | `shape_mouth_width_up / shape_mouth_width_dn` | `weight` | -1~+1 | 0 | mouth_corner_up | 保留 |
| E 嘴巴 | 嘴巴高度 | `mouth_height` | `morph` | `shape_mouth_height_up / shape_mouth_height_dn` | `weight` | -1~+1 | 0 | philtrum_length | 保留 |
| E 嘴巴 | 上唇厚度 | `lip_upper_thickness` | `morph` | `shape_lip_upper_thickness_up / shape_lip_upper_thickness_dn` | `weight` | -1~+1 | 0 | lip_shape | 保留 |
| E 嘴巴 | 下唇厚度 | `lip_lower_thickness` | `morph` | `shape_lip_lower_thickness_up / shape_lip_lower_thickness_dn` | `weight` | -1~+1 | 0 | lip_shape | 保留 |
| E 嘴巴 | 唇形 | `lip_shape` | `morph` | `shape_lip_shape` | `enum` | 6 档 | 标准唇 | lip_upper_thickness | 保留 |
| E 嘴巴 | 嘴角上扬 | `mouth_corner_up` | `morph` | `shape_mouth_corner_up_up / shape_mouth_corner_up_dn` | `weight` | -1~+1 | 0 | mouth_width | 保留 |
| E 嘴巴 | 嘴巴前突 | `mouth_protrusion` | `morph` | `shape_mouth_protrusion_up / shape_mouth_protrusion_dn` | `weight` | -1~+1 | 0 | lip_upper_thickness | 保留 |
| E 嘴巴 | 人中长度 | `philtrum_length` | `morph` | `shape_philtrum_length_up / shape_philtrum_length_dn` | `weight` | -1~+1 | 0 | mouth_height | 保留 |
| E 嘴巴 | 人中深浅 | `philtrum_depth` | `morph` | `shape_philtrum_depth` | `weight` | 0~1 | 0 | philtrum_length | 保留 |
| E 嘴巴 | 牙齿大小 | `teeth_size` | `morph` | `shape_teeth_size_up / shape_teeth_size_dn` | `weight` | -1~+1 | 0 | mouth_width | 保留 |
| E 嘴巴 | 牙齿颜色 | `teeth_color` | `material` | `teeth_color` | `color` | 色板 5 档 | 自然白 | lip_color | 保留 |
| E 嘴巴 | 唇色 | `lip_color` | `material` | `lip_color` | `color` | 色板 10 档 | 自然粉 | makeup_preset | 保留 |
| F 耳朵 | 耳朵大小 | `ear_size` | `bone` | `ear.L/ear.R` | `scale` | 0.90~1.10 | 1.0 | ear_height | 保留 |
| F 耳朵 | 外张角度 | `ear_protrusion` | `bone` | `ear.L/ear.R` | `rotate` | +/-8 deg | 0 | ear_size | 保留 |
| F 耳朵 | 高低位置 | `ear_height` | `bone` | `ear.L/ear.R` | `translate` | +/-3 mm | 0 | ear_protrusion | 保留 |
| F 耳朵 | 耳垂大小 | `ear_lobe_size` | `morph` | `shape_ear_lobe_size_up / shape_ear_lobe_size_dn` | `weight` | -1~+1 | 0 | ear_shape | 保留 |
| F 耳朵 | 耳廓形状 | `ear_shape` | `morph` | `shape_ear_shape_up / shape_ear_shape_dn` | `weight` | -1~+1 | 0 | ear_lobe_size | 保留 |
| G 皮肤与年龄感 | 肤色 | `skin_tone` | `material` | `skin_base_color` | `color` | 色板 12 档 | 自然偏暖 | age_overall | 保留 |
| G 皮肤与年龄感 | 皮肤质感 | `skin_texture` | `material` | `skin_roughness` | `weight` | 0~1 | 0.4 | age_overall | 保留 |
| G 皮肤与年龄感 | 油光度 | `oiliness` | `material` | `skin_specular` | `weight` | 0~1 | 0.3 | skin_texture | 弱化 |
| G 皮肤与年龄感 | 额头纹 | `forehead_wrinkle` | `morph` | `shape_wrinkle_forehead` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 眉间纹 | `frown_line` | `morph` | `shape_wrinkle_glabella` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 法令纹 | `nasolabial` | `morph` | `shape_wrinkle_nasolabial` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 鱼尾纹 | `crow_feet` | `morph` | `shape_wrinkle_crowfeet` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 嘴角纹 | `mouth_line` | `morph` | `shape_wrinkle_mouthcorner` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 颈纹 | `neck_wrinkle` | `morph` | `shape_wrinkle_neck` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 年龄感 | `age_overall` | `morph` | `shape_age_overall` | `weight` | 0~1 | 0 | 全部皱纹 + skin_texture + cheek_fullness + eye_bag | 保留 |
| G 皮肤与年龄感 | 老年斑强度 | `age_spot` | `material` | `age_spot_mask` | `weight` | 0~1 | 0 | age_overall | 保留 |
| G 皮肤与年龄感 | 黑眼圈 | `dark_circle` | `material` | `dark_circle_mask` | `weight` | 0~1 | 0 | age_overall | 保留 |
| H 妆容（裁剪版） | 眼影色板 | `eyeshadow_color` | `material` | `eyeshadow_color` | `color` | 色板 8 档 | 不化妆（透明） | eyeshadow_strength | 弱化 |
| H 妆容（裁剪版） | 眼影强度 | `eyeshadow_strength` | `material` | `eyeshadow_mask` | `weight` | 0~1 | 0 | eyeshadow_color | 弱化 |
| H 妆容（裁剪版） | 眼线粗细 | `eyeliner_width` | `material` | `eyeliner_mask` | `weight` | 0~1 | 0 | eyeliner_color | 弱化 |
| H 妆容（裁剪版） | 眼线颜色 | `eyeliner_color` | `material` | `eyeliner_color` | `color` | 色板 4 档 | 自然黑 | eyeliner_width | 弱化 |
| H 妆容（裁剪版） | 腮红色板 | `blush_color` | `material` | `blush_color` | `color` | 色板 8 档 | 不化妆（透明） | blush_strength | 弱化 |
| H 妆容（裁剪版） | 腮红强度 | `blush_strength` | `material` | `blush_mask` | `weight` | 0~1 | 0 | blush_color | 弱化 |
| H 妆容（裁剪版） | 腮红位置 | `blush_position` | `material` | `blush_offset` | `enum` | 2 档（苹果肌/颧骨） | 苹果肌 | blush_strength | 弱化 |
| H 妆容（裁剪版） | 修容强度 | `contour_strength` | `material` | `contour_mask` | `weight` | 0~1 | 0 | highlight_strength | 弱化 |
| H 妆容（裁剪版） | 高光强度 | `highlight_strength` | `material` | `highlight_mask` | `weight` | 0~1 | 0 | contour_strength | 弱化 |
| H 妆容（裁剪版） | 妆容方案 | `makeup_preset` | `material` | `makeup_set` | `enum` | 3 档 | 不化妆 | 眼影/眼线/腮红/修容/高光 全部联动 | 弱化 |
| I 头发与胡须 | 发型 | `hairstyle` | `asset` | `hair_slot` | `enum` | 12 款 | 自然短发 | bangs | 保留 |
| I 头发与胡须 | 发色 | `hair_color` | `material` | `hair_color` | `color` | 色板 16 档 | 自然黑 | white_hair_ratio | 保留 |
| I 头发与胡须 | 刘海 | `bangs` | `asset` | `bangs_slot` | `enum` | 6 款 | 无刘海 | hairstyle | 保留 |
| I 头发与胡须 | 白发比例 | `white_hair_ratio` | `material` | `hair_white_mask` | `weight` | 0~1 | 0 | age_overall | 保留 |
| I 头发与胡须 | 胡须类型 | `beard_type` | `asset` | `beard_slot` | `enum` | 0 款（本档不做） | 无 | - | 不做 |
| I 头发与胡须 | 胡须浓密度 | `beard_density` | `asset` | `beard_density` | `weight` | 0~1 | 0 | - | 不做 |
| I 头发与胡须 | 胡须颜色 | `beard_color` | `material` | `beard_color` | `color` | 色板 8 档 | 自然黑 | - | 不做 |
| J 身体细节 | 肩宽 | `shoulder_width` | `morph` | `shape_shoulder_width_up / shape_shoulder_width_dn` | `weight` | -1~+1 | 0 | neck_length | 弱化 |
| J 身体细节 | 脖子长度 | `neck_length` | `morph` | `shape_neck_length_up / shape_neck_length_dn` | `weight` | -1~+1 | 0 | shoulder_width | 保留 |
| J 身体细节 | 头身比 | `head_scale` | `bone` | `head` | `scale` | 0.92~1.08 | 1.0 | shoulder_width | 弱化 |

## 明确不做（康养裁剪，规格书第一部分）

- 战斗/异族妆容、面部彩绘、纹身、异色瞳（`pupil_color` 只保留 6 档自然色板）
- 极端体型与极端五官形变（所有 morph 幅度按毫米级标定，见交付说明第 18 章）
- 兽耳/非人类面部结构
- 伤疤/残疾类特征
- `beard_*` 3 条对女性 60+ 档标为 `不做`（不建资产槽、端侧隐藏该组滑杆）

## 来源与核对状态

分区结构依据 2021-06-22 公开攻略（游侠网《永劫无间》捏脸功能介绍）；A–G 分区条数对齐规格书第三部分给出的骨架；细分滑杆于 2026-09-30 由本项目自定，待【附录B】对照游戏界面人工核对，核对结论回填后升版为 1.1.0。

## 自检（规格书第十部分第 1–3、13 条）

1. 覆盖 A–J 十个分区，总数 102 ≥ 100，每条 10 列完整。 
2. A–G 每区条数：A=17、B=8、C=18、D=10、E=12、F=5、G=12，均 ≥ 规格书给的下限（15/7/15/10/11/5/12）。 
3. 每条参数只落一个通道；分工见交付说明 18.2，无同一区域被骨骼与 morph 同时强驱动。 
13. `老人可用性` 逐条标注：保留 79、弱化 20、不做 3（三类之和 = 102），另标 15 条「保留并强化」（肤色 / 皮肤质感 / 6 处皱纹 / 年龄感 / 老年斑 / 黑眼圈 / 白发比例 / 发型发色刘海）。理由逐条见 `client/care-trim.js`；本列由 `_mk_params_el.mjs` 生成，与裁剪表逐条一致才通过校验。
