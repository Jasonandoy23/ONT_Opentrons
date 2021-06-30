def get_values(*names):
    import json
    _all_values = json.loads("""{"samples":96,"m300_mount":"right","p300_mount":"left","mag_engage_height":7.8}""")
    return [_all_values[n] for n in names]


from opentrons import protocol_api, types
import math
import pandas as pd
import csv

metadata = {
    'protocolName': 'Ligation Sequencing Kit: DNA Repair and End-Prep',
    'author': 'Kenshin <boss.kenshin@g42.ai>',
    'description': 'Custom Protocol Request',
    'apiLevel': '2.10'
}

Source_position = []
Target_position = []

file_input_ot2 = '/data/user_files/input.csv'

df = pd.read_csv(file_input_ot2)

for i in range(len(df)):
    Source_position.append(df['Source'][i])
    Target_position.append(df['Target'][i])


def run(ctx):
    [samples, m300_mount, p300_mount,
     mag_engage_height] = get_values(  # noqa: F821
        "samples", "m300_mount", "p300_mount", "mag_engage_height")

    cols = math.ceil(len(df) / 8)
    ctx.set_rail_lights(True)
    # Load Labware
    tc_mod = ctx.load_module('Thermocycler Module')
    tc_plate = tc_mod.load_labware('biorad_96_wellplate_200ul_pcr')
    mag_mod = ctx.load_module('magnetic module gen2', '1')
    mag_plate = mag_mod.load_labware('thermofisher_96_midi_storage_plate_800ul')
    temp_mod = ctx.load_module('temperature module gen2', 4)
    temp_rack = temp_mod.load_labware('opentrons_24_aluminumblock_generic_2ml_screwcap')
    final_plate = ctx.load_labware('biorad_96_wellplate_200ul_pcr', 2)
    reservoir = ctx.load_labware('nest_12_reservoir_15ml', 3)
    tipracks_multi = [ctx.load_labware('opentrons_96_tiprack_300ul', slot) for slot in [6, 9]]
    tipsracks_single = ctx.load_labware('opentrons_96_tiprack_300ul', 5)
    trash = ctx.loaded_labwares[12]['A1']

    # Load Pipettes
    m300 = ctx.load_instrument('p300_multi_gen2', m300_mount,
                               tip_racks=tipracks_multi)
    p300 = ctx.load_instrument('p300_single_gen2', p300_mount,
                               tip_racks=[tipsracks_single])

    # Reagents
    ampure_beads = reservoir['A12']
    nfa = reservoir['A5']
    mm = temp_rack['A1']

    # Sample Wells
    # tc_plate_wells = tc_plate.wells()[0]
    tc_plate_wells = tc_plate.rows()[0][:cols]
    mag_plate_wells = mag_plate.rows()[0][:cols]
    final_plate_wells = final_plate.rows()[0][:cols]

    # Helper Functions
    def pick_up(pip):
        """Function that can be used instead of .pick_up_tip() that will pause
        robot when robot runs out of tips, prompting user to replace tips
        before resuming"""
        try:
            pip.pick_up_tip()
        except protocol_api.labware.OutOfTipsError:
            pip.home()
            ctx.pause("Replace the tips")
            pip.reset_tipracks()
            pip.pick_up_tip()

    def remove_supernatant(vol, src, dest, side):
        m300.flow_rate.aspirate = 20
        m300.aspirate(10, src.top())
        while vol > 300:
            m300.aspirate(
                300, src.bottom().move(types.Point(x=side, y=0, z=0.5)))
            m300.dispense(300, dest)
            m300.aspirate(10, dest)
            vol -= 300
        m300.aspirate(vol, src.bottom().move(types.Point(x=side, y=0, z=0.5)))
        m300.dispense(vol, dest)
        m300.dispense(10, dest)
        m300.flow_rate.aspirate = 50

    sides = [-1, 1] * 6
    sides = sides[:cols]

    def magnet(delay_mins):
        mag_mod.engage(height_from_base=mag_engage_height)
        ctx.delay(minutes=delay_mins, msg='Allowing beads to settle.')

    # Volume Tracking
    class VolTracker:
        def __init__(self, labware, well_vol, pip_type='single',
                     mode='reagent', start=0, end=12, msg='Reset Labware'):
            try:
                self.labware_wells = dict.fromkeys(
                    labware.wells()[start:end], 0)
            except Exception:
                self.labware_wells = dict.fromkeys(
                    labware, 0)
            self.labware_wells_backup = self.labware_wells.copy()
            self.well_vol = well_vol
            self.pip_type = pip_type
            self.mode = mode
            self.start = start
            self.end = end
            self.msg = msg

        def tracker(self, vol):
            '''tracker() will track how much liquid
            was used up per well. If the volume of
            a given well is greater than self.well_vol
            it will remove it from the dictionary and iterate
            to the next well which will act as the reservoir.'''
            well = next(iter(self.labware_wells))
            if self.labware_wells[well] + vol >= 14800:
                del self.labware_wells[well]
                if len(self.labware_wells) < 1:
                    ctx.pause(self.msg)
                    self.labware_wells = self.labware_wells_backup.copy()
                well = next(iter(self.labware_wells))
            if self.pip_type == 'multi':
                self.labware_wells[well] = self.labware_wells[well] + vol * 8
            elif self.pip_type == 'single':
                self.labware_wells[well] = self.labware_wells[well] + vol
            if self.mode == 'waste':
                ctx.comment(f'''{well}: {int(self.labware_wells[well])} uL of
                            total waste''')
            else:
                ctx.comment(f'''{int(self.labware_wells[well])} uL of liquid
                            used from {well}''')
            return well

    ethanolTrack = VolTracker(reservoir, 14900, 'multi', start=0, end=4,
                              msg='Replenish Ethanol')

    # PROTOCOL STEPS
    # Set Temperature Module to 6C


    # Transfer End Prep Mix to Samples on PCR Plate (1)
    def transfer_endprepmix():
        temp_mod.set_temperature(8)
        for i in range(len(Target_position)):
            #         p300.pick_up_tip()
            #         p300.aspirate(12, mm)

            #         p300.dispense(12, tc_plate[Target_position[i]])
            #         p300.mix(3, 30, tc_plate[Target_position[i]])
            #         p300.blow_out()
            #         p300.drop_tip(home_after=False)
            p300.transfer(12, mm, tc_plate[Target_position[i]], new_tip='always',
                          mix_after=(3, 30), trash=False)
            # p300.drop_tip(home_after=False)
        temp_mod.deactivate()

    # Pause for Spin Down (2)
    def spindown_thermocycler_process():
        ctx.pause('Spin down the plate while Thermocycler pre heating to 20C is ongoing and resume.')
        #
        # # Pre-Heat Thermocycler to 20C
        # ctx.pause('Pre-Heating the thermocycler to 20C.')
        tc_mod.set_block_temperature(20)
        tc_mod.set_lid_temperature(70)
        ctx.pause('Put the sample plate into the thermocycler')

        # Incubate on Thermocycler (3)
        tc_mod.close_lid()
        profile = [{'temperature': 20, 'hold_time_minutes': 5},
                   {'temperature': 65, 'hold_time_minutes': 5}]
        tc_mod.execute_profile(steps=profile, repetitions=1, block_max_volume=60)
        tc_mod.open_lid()
        tc_mod.deactivate()

    # Resuspend AMPure Beads (4)
    #     m300.pick_up_tip()
    #     m300.mix(5, 300, ampure_beads.bottom(z=3))
    #     m300.drop_tip()

    # Add AMPure XP Beads to Mag Mod (6-7)
    def adding_ampurebeads():
        ctx.pause('''Add Ampure Beads manually to reservoir in slot 3 Position 12.''')
        pick_up(m300)
        for well in mag_plate_wells:
            m300.transfer(60, ampure_beads, well, new_tip='never',
                          mix_before=(3, 60))
        m300.drop_tip()

    # Transfer Samples from TC to Mag Mod (5)
    def transfer_samples_f_TC():
        # m300.drop_tip()
        for src, dest in zip(tc_plate_wells, mag_plate_wells):
            # m300.pick_up_tip()
            m300.transfer(60, src, dest, new_tip='always', mix_after=(5, 60), trash=False)
            # m300.drop_tip()

    # Pause for Hula Mixer/Spin Down (8-9)
    def incubate_time1():
        ctx.pause('''Incubate on Hula Mixer for 5 minutes and spin down the samples.
                    Then place back on the magnet and click resume.''')

    # Engage Magnet and Delay for 5 Minutes (10)
    def magnet_removesupernatant():
        magnet(5)
        # Remove Supernatant (11)
        for well, side in zip(mag_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(200, well, trash, side)
            m300.drop_tip()

    # (12-14)# Wash Beads with Ethanol (12)
    def washing_step():
        for _ in range(2):
            # Wash Beads with Ethanol (12)
            for well in mag_plate_wells:
                pick_up(m300)
                m300.aspirate(200, ethanolTrack.tracker(200))
                m300.dispense(200, well.top(-3))
                m300.mix(3, 100)
                m300.drop_tip()

            # Remove Supernatant (11)
            for well, side in zip(mag_plate_wells, sides):
                pick_up(m300)
                remove_supernatant(100, well, trash, side)
                m300.drop_tip()

    # Pause and Remove Samples for Spin Down (15)
    def pause_spindown_remove_samples():
        mag_mod.disengage()
        ctx.pause('''Spin down and place samples back on the maget.
                 Then click resume.''')
        magnet(1)

        # Remove Residual Ethanol (16)
        for well, side in zip(mag_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(100, well, trash, side)
            m300.drop_tip()

        # Add 61 uL of Nuclease-free Water (17)
        mag_mod.disengage()

    # Transfer 61 EB to MIDI plate
    def transfer_eb_midi():
        m300.home()
        ctx.pause("Replace the tips")
        m300.reset_tipracks()
        for well in mag_plate_wells:
            m300.transfer(61, nfa, well.top(-3), mix_after=(3, 60), new_tip='always', trash=False)

        ctx.pause('''Shake, spin down and incubate at Room Temperature for 10 minutes.''')

        # Engage Magnet (18)
        magnet(5)

    # Transfer Eluate into PCRplate plate for part 2 (19)
    def transfer_final_result():
        for well, dest, side in zip(mag_plate_wells, final_plate_wells, sides):
            pick_up(m300)
            remove_supernatant(100, well, dest, side)
            m300.drop_tip()

        temp_mod.deactivate()
        mag_mod.disengage()
        ctx.set_rail_lights(False)

    transfer_endprepmix()
    spindown_thermocycler_process()
    adding_ampurebeads()
    transfer_samples_f_TC()
    incubate_time1()
    magnet_removesupernatant()
    washing_step()
    pause_spindown_remove_samples()
    transfer_eb_midi()
    transfer_final_result()
